import os
import math
import resend
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client

# 1. Initialize FastAPI Application
app = FastAPI(title="MindStormerX Live Production API")

# 2. Configure CORS Security Middleware for Live Production Domains
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

# 3. Initialize Production API Engines (Supabase + Resend)
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

resend.api_key = os.environ.get("RESEND_API_KEY")


# ==========================================
#        DATA VALIDATION SCHEMAS
# ==========================================

class JobSubmission(BaseModel):
    full_name: str
    email: str
    phone_number: str  # Client's WhatsApp number
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
    return c * 6371.0  # Earth's radius in kilometers


# ==========================================
#             SYSTEM ENDPOINTS
# ==========================================

@app.api_route("", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/health", methods=["GET", "HEAD"], include_in_schema=False)
async def root_health_check():
    return {"status": "healthy", "service": "MindStormerX Live Grid"}


# Route 1: Production Client Booking & Real-Time Proximity Routing Engine
@app.post("/jobs", status_code=201)
async def create_job(job: JobSubmission):
    if not supabase:
        raise HTTPException(status_code=500, detail="Database connection parameters are misconfigured.")

    # 1. Persist client job entry directly into your database
    job_insert = supabase.table("jobs").insert({
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

    # 2. Query dynamic technicians matching the specific service type/trade category
    tech_query = supabase.table("technicians").select("*").eq("trade", job.category.lower()).execute()
    available_technicians = tech_query.data

    # Fallback to general technicians roster if trade query yields empty sets
    if not available_technicians:
        tech_query = supabase.table("technicians").select("*").execute()
        available_technicians = tech_query.data

    if not available_technicians:
        raise HTTPException(status_code=404, detail="No field technicians currently registered on the grid.")

    # 3. Process Live Proximity Match
    assigned_tech = None
    shortest_distance = float('inf')
    
    for tech in available_technicians:
        # Pulling geographical coordinates dynamically stored inside database table columns
        tech_lat = float(tech.get("latitude") or 0.0)
        tech_lng = float(tech.get("longitude") or 0.0)
        
        distance = calculate_proximity(job.client_lat, job.client_lng, tech_lat, tech_lng)
        if distance < shortest_distance:
            shortest_distance = distance
            assigned_tech = tech

    # 4. Generate Live External Tracking Deep Links
    live_location_url = f"https://www.google.com/maps/search/?api=1&query={job.client_lat},{job.client_lng}"
    whatsapp_direct_url = f"https://wa.me/{job.phone_number.replace('+', '').replace(' ', '')}"

    try:
        # A. Notification Dispatch directly to the matched Technician's dynamic real email
        resend.Emails.send({
            "from": "MindStormerX Dispatch <alerts@mayndstomir.com>",
            "to": [assigned_tech["email"]],  # Dynamically pulled directly from database row
            "subject": "🚨 Urgent: New Client Assigned in Your Proximity",
            "html": f"""
            <h3>🛠️ Service Request Assigned</h3>
            <p>Hello {assigned_tech['full_name']}, you have been automatically assigned a new service request based on proximity criteria.</p>
            <hr/>
            <p><strong>Client Name:</strong> {job.full_name}</p>
            <p><strong>Job Details / Issue:</strong> {job.description}</p>
            <p><strong>Scheduled Slot:</strong> {job.preferred_date} at {job.preferred_time}</p>
            <br/>
            <p><strong>📱 Client WhatsApp Thread:</strong> <a href="{whatsapp_direct_url}">Chat with Client ({job.phone_number})</a></p>
            <p><strong>📍 Navigation Tracking Coordinates:</strong> <a href="{live_location_url}" target="_blank">Launch Live Turn-by-Turn Map Route</a></p>
            """
        })
        
        # B. Confirmation Dispatch Payload directly to Client
        resend.Emails.send({
            "from": "MindStormerX <support@mayndstomir.com>",
            "to": [job.email], 
            "subject": "🛠️ Technician Dispatched! Your Service is Confirmed",
            "html": f"""
            <h3>Hi {job.full_name},</h3>
            <p>Your application has been received and processed successfully.</p>
            <p><strong>Good news:</strong> A technician has already been matched to your location based on proximity constraints!</p>
            <hr/>
            <p><strong>Assigned Professional:</strong> {assigned_tech['full_name']}</p>
            <p><strong>Contact Direct Line:</strong> {assigned_tech['phone_number']}</p>
            <br/>
            <p>They are currently reviewing your description details and will connect with you shortly.</p>
            <br/>
            <p>Best regards,<br/>The MindStormerX Team</p>
            """
        })
    except Exception as e:
        print(f"Operational production mail routing warning: {str(e)}")

    return {
        "status": "success", 
        "message": "Application accepted and proximity route assigned.",
        "popup_data": {
            "client_notice": "Application submitted! A field technician has been successfully matched to your location.",
            "technician_notice": f"New client request received. Order assigned to closest node: {assigned_tech['full_name']}.",
            "matched_technician": {
                "name": assigned_tech["full_name"],
                "phone": assigned_tech["phone_number"]
            }
        }
    }


# Route 2: Live Onboarding Endpoint for Freelance Technicians
@app.post("/freelance_applications", status_code=201)
async def register_technician(tech: TechnicianApplication):
    if not supabase:
        raise HTTPException(status_code=500, detail="Database connection parameters are misconfigured.")

    # 1. Insert applicant data into production database table row 
    supabase.table("technicians").insert({
        "full_name": tech.full_name,
        "phone_number": tech.phone_number,
        "email": tech.email,
        "trade": tech.trade.lower(),
        "experience_years": tech.experience_years,
        "qid_number": tech.qid_number,
        "kahramaa_id": tech.kahramaa_id,
        "id_photo_url": tech.id_photo_url,
        "latitude": 25.2854,  # Defaults to core metro zone coordinates upon application sign-up
        "longitude": 51.5310
    }).execute()
    
    try:
        # 2. Administrative internal email notification layout
        resend.Emails.send({
            "from": "MindStormerX Core <alerts@mayndstomir.com>",
            "to": ["viewwhatsappstatus@gmail.com"],  # Your core internal project monitoring hub
            "subject": f"📋 New Technician Applicant Onboarded: {tech.full_name}",
            "html": f"""
            <h3>New Freelance Onboarding Application</h3>
            <p><strong>Name:</strong> {tech.full_name}</p>
            <p><strong>Phone:</strong> {tech.phone_number}</p>
            <p><strong>Email:</strong> {tech.email}</p>
            <p><strong>Trade/Specialty:</strong> {tech.trade.upper()}</p>
            <p><strong>Years of Experience:</strong> {tech.experience_years}</p>
            <p><strong>QID:</strong> {tech.qid_number}</p>
            <p><strong>Kahramaa ID:</strong> {tech.kahramaa_id}</p>
            <p><strong>ID Photo Link:</strong> <a href="{tech.id_photo_url}" target="_blank">View Uploaded ID Document</a></p>
            """
        })
    except Exception as e:
        print(f"Freelancer onboarding tracking notice: {str(e)}")

    return {
        "status": "success",
        "message": "Application submitted successfully!",
        "popup_data": {
            "technician_notice": "Your application has been received! We will review your details and contact you via WhatsApp shortly."
        }
    }