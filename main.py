import os
import math
import resend
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client

app = FastAPI(title="MindStormerX Production Network")

# Bulletproof CORS Configuration
origins = [
    "https://www.mayndstomir.com",
    "https://mayndstomir.com",
    "http://localhost:3000",
    "http://localhost:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global error shield to prevent silent crashes and reveal true DB errors
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": f"Server Exception: {str(exc)}"},
        headers={"Access-Control-Allow-Origin": "*"}
    )

# Connect to Supabase Safely
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None
except Exception:
    supabase = None

# Initialize Resend Email Engine Safely inside endpoints to avoid startup crashes
def get_resend_client():
    api_key = os.environ.get("RESEND_API_KEY")
    if api_key:
        resend.api_key = api_key
        return resend
    return None


# ==========================================
#        DATA VALIDATION SCHEMAS
# ==========================================

class JobSubmission(BaseModel):
    full_name: str
    email: str
    phone_number: str  
    category: str
    description: str
    preferred_date: str
    preferred_time: str
    client_lat: float  
    client_lng: float  

class TechnicianApplication(BaseModel):
    full_name: str
    phone_number: str
    email: str
    trade: str
    experience_years: int  
    qid_number: str
    kahramaa_id_url: str  # CHANGED: Now expects an uploaded document image URL per boss instructions
    id_photo_url: str


# ==========================================
#          GEOSPATIAL CORE LOGIC
# ==========================================

def calculate_proximity(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    rad_lat1, rad_lon1, rad_lat2, rad_lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlon = rad_lon2 - rad_lon1
    dlat = rad_lat2 - rad_lat1
    a = math.sin(dlat/2)**2 + math.cos(rad_lat1) * math.cos(rad_lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    return c * 6371.0  


# ==========================================
#             SYSTEM ENDPOINTS
# ==========================================

@app.get("/")
async def root_health_check():
    return {"status": "healthy"}


# Route 1: Client Booking & Dispatches Proximity Email
@app.post("/jobs")
async def create_job(job: JobSubmission):
    if not supabase:
        return JSONResponse(status_code=500, content={"error": "Database credentials uninitialized."})

    try:
        # Determine active jobs table variant
        job_table = "freelance_applications"
        for t_name in ["jobs", "job", "service_requests"]:
            try:
                supabase.table(t_name).select("id").limit(1).execute()
                job_table = t_name
                break
            except Exception:
                continue

        # Insert client job
        supabase.table(job_table).insert({
            "full_name": job.full_name,
            "email": job.email,
            "phone_number": job.phone_number,
            "category": job.category,
            "description": job.description,
            "preferred_date": job.preferred_date,
            "preferred_time": job.preferred_time,
            "latitude": job.client_lat,
            "longitude": job.client_lng
        }).execute()

        # Find technicians table name variant
        tech_table = "freelance_applications"
        for t_name in ["freelance_applications", "technicians", "technician"]:
            try:
                supabase.table(t_name).select("id").limit(1).execute()
                tech_table = t_name
                break
            except Exception:
                continue

        # Query all field technicians
        tech_query = supabase.table(tech_table).select("*").execute()
        available_technicians = tech_query.data

        if not available_technicians:
            return JSONResponse(status_code=404, content={"error": "No technicians found in database to assign."})

        # Calculate closest technician
        assigned_tech = available_technicians[0]
        shortest_distance = float('inf')
        
        for tech in available_technicians:
            tech_lat = float(tech.get("latitude") or 25.2854)
            tech_lng = float(tech.get("longitude") or 51.5310)
            distance = calculate_proximity(job.client_lat, job.client_lng, tech_lat, tech_lng)
            if distance < shortest_distance:
                shortest_distance = distance
                assigned_tech = tech

        # Generate URLs for the technician dispatch email
        live_location_url = f"https://www.google.com/maps/search/?api=1&query={job.client_lat},{job.client_lng}"

        # Send emails via Resend
        mail_engine = get_resend_client()
        if mail_engine:
            try:
                # Send critical details directly to the assigned tech's inbox
                mail_engine.Emails.send({
                    "from": "MindStormerX Dispatch <alerts@mayndstomir.com>",
                    "to": [assigned_tech.get("email")],
                    "subject": "🚨 Job Assigned: Live Location and Client Details Enclosed",
                    "html": f"""
                    <h3>🛠️ New Service Assignment</h3>
                    <p>You have been routed to a new job based on closest proximity parameters.</p>
                    <hr/>
                    <p><strong>Client Contact Number:</strong> {job.phone_number}</p>
                    <p><strong>Issue to Fix / Description:</strong> {job.description}</p>
                    <p><strong>Scheduled Time:</strong> {job.preferred_date} at {job.preferred_time}</p>
                    <br/>
                    <p><strong>📍 LIVE CLIENT LOCATION MAP LINK:</strong> <a href="{live_location_url}" target="_blank" style="background-color: #25D366; color: white; padding: 10px 15px; text-decoration: none; border-radius: 5px; display: inline-block;">Open Live Navigation Route</a></p>
                    <br/>
                    <p>Please connect with the client immediately via their phone number.</p>
                    """
                })
            except Exception as email_err:
                print(f"Email failure: {email_err}")

        return {
            "status": "success",
            "message": "Job successfully routed to nearest technician.",
            "matched_technician": assigned_tech.get("full_name")
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Job processing crashed: {str(e)}"})


# Route 2: Onboarding Endpoint (Accepts Image Upload URL for Kahramaa ID)
@app.post("/freelance_applications")
async def register_technician(tech: TechnicianApplication):
    if not supabase:
        return JSONResponse(status_code=500, content={"error": "Database credentials uninitialized."})

    insert_data = {
        "full_name": tech.full_name,
        "phone_number": tech.phone_number,
        "email": tech.email,
        "trade": tech.trade.lower(),
        "experience_years": tech.experience_years,
        "qid_number": tech.qid_number,
        "kahramaa_id_url": tech.kahramaa_id_url,  # Saves the image upload reference path cleanly
        "id_photo_url": tech.id_photo_url,
        "latitude": 25.2854,  
        "longitude": 51.5310
    }

    # Bypasses PGRST125 table errors by checking your dashboard variants safely
    db_success = False
    last_err = ""
    
    for table_name in ["freelance_applications", "technicians", "technician"]:
        try:
            supabase.table(table_name).insert(insert_data).execute()
            db_success = True
            break
        except Exception as e:
            last_err = str(e)
            if "PGRST125" not in last_err:
                return JSONResponse(status_code=500, content={"error": f"Schema field mismatch error: {last_err}"})
            continue

    if not db_success:
        return JSONResponse(status_code=500, content={"error": f"Could not map database destination: {last_err}"})
        
    return {
        "status": "success",
        "message": "Application uploaded and logged successfully!"
    }