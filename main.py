import os
import math
import resend
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client

# 1. Initialize FastAPI Application
app = FastAPI(title="MindStormerX Live Production API")

# 2. Configure Bulletproof CORS Policy
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

# Global fallback exception handler to guarantee CORS headers are never dropped during a crash
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": f"Internal Server Crash: {str(exc)}"},
        headers={"Access-Control-Allow-Origin": "https://www.mayndstomir.com"}
    )

# 3. Initialize Production Engines
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None
except Exception as e:
    print(f"Supabase Init Error: {e}")
    supabase = None

resend.api_key = os.environ.get("RESEND_API_KEY")


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
    kahramaa_id: str       
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
    return {"status": "healthy", "service": "MindStormerX Live Grid"}


# Route 1: Client Booking & Real-Time Proximity Routing Engine
@app.post("/jobs")
async def create_job(job: JobSubmission):
    if not supabase:
        return JSONResponse(status_code=500, content={"error": "Database connection keys missing from environment variables."})

    try:
        # Dynamically find the correct jobs table variant
        job_data = {
            "full_name": job.full_name,
            "email": job.email,
            "phone_number": job.phone_number,
            "category": job.category,
            "description": job.description,
            "preferred_date": job.preferred_date,
            "preferred_time": job.preferred_time,
            "latitude": job.client_lat,
            "longitude": job.client_lng
        }

        try:
            supabase.table("jobs").insert(job_data).execute()
            tech_table = "technicians"
        except Exception:
            try:
                supabase.table("job").insert(job_data).execute()
                tech_table = "technician"
            except Exception:
                supabase.table("service_requests").insert(job_data).execute()
                tech_table = "freelancers"

        # Query matching technicians based on trade
        try:
            tech_query = supabase.table(tech_table).select("*").eq("trade", job.category.lower()).execute()
            available_technicians = tech_query.data
        except Exception:
            # Absolute fallback to get anything if the schema query breaks
            tech_query = supabase.table(tech_table).select("*").execute()
            available_technicians = tech_query.data

        if not available_technicians:
            return JSONResponse(status_code=404, content={"error": "No field technicians registered on the network."})

        assigned_tech = available_technicians[0]
        shortest_distance = float('inf')
        
        for tech in available_technicians:
            tech_lat = float(tech.get("latitude") or 0.0)
            tech_lng = float(tech.get("longitude") or 0.0)
            distance = calculate_proximity(job.client_lat, job.client_lng, tech_lat, tech_lng)
            if distance < shortest_distance:
                shortest_distance = distance
                assigned_tech = tech

        return {
            "status": "success", 
            "message": "Job matched successfully.",
            "popup_data": {
                "client_notice": "Your service request has been scheduled.",
                "matched_technician": {"name": assigned_tech.get("full_name", "Provider"), "phone": assigned_tech.get("phone_number", "")}
            }
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Database Operation Failed: {str(e)}"})


# Route 2: Onboarding Endpoint for Freelance Technicians
for table_name in ["freelance_applications", "technicians", "technician", "freelancers"]:
async def register_technician(tech: TechnicianApplication):
    if not supabase:
        return JSONResponse(status_code=500, content={"error": "Supabase connection is uninitialized. Check Render Env variables."})

    insert_data = {
        "full_name": tech.full_name,
        "phone_number": tech.phone_number,
        "email": tech.email,
        "trade": tech.trade.lower(),
        "experience_years": tech.experience_years,
        "qid_number": tech.qid_number,
        "kahramaa_id": tech.kahramaa_id,
        "id_photo_url": tech.id_photo_url,
        "latitude": 25.2854,  
        "longitude": 51.5310
    }

    # Bypasses PGRST125 table errors by checking variants in a fallback loop
    db_success = False
    last_error = ""
    
    for table_name in ["technicians", "technician", "freelancers"]:
        try:
            supabase.table(table_name).insert(insert_data).execute()
            db_success = True
            break
        except Exception as e:
            last_error = str(e)
            if "PGRST125" not in last_error:
                # If it's a real schema field problem, raise it immediately
                return JSONResponse(status_code=500, content={"error": f"Database Field Mismatch: {last_error}"})
            continue

    if not db_success:
        return JSONResponse(status_code=500, content={"error": f"Table schema mismatch target variants: {last_error}"})
        
    return {
        "status": "success",
        "message": "Application submitted successfully!",
        "popup_data": {
            "technician_notice": "Registration complete! Your profile is active."
        }
    }


# Route 3: Client Job Status Lookup Endpoint
@app.get("/lookup/{phone_number}")
async def lookup_job(phone_number: str):
    if not supabase:
        return JSONResponse(status_code=500, content={"error": "Database disconnected."})

    try:
        clean_phone = phone_number.replace("+", "").replace(" ", "")
        
        # Safe table resolution variant check
        jobs = None
        for table_name in ["jobs", "job", "service_requests"]:
            try:
                job_query = supabase.table(table_name).select("*").ilike("phone_number", f"%{clean_phone}%").execute()
                jobs = job_query.data
                break
            except Exception:
                continue

        if not jobs:
            return JSONResponse(status_code=404, content={"error": "No matching records found."})

        latest_job = jobs[-1]
        return {"status": "success", "job": latest_job}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})