import os
import math
import resend
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# 1. Initialize FastAPI Application
app = FastAPI(title="MindStormerX Master API")

# 2. Configure CORS Security Middleware (Resolves the browser block)
origins = [
    "https://www.mayndstomir.com",
    "https://mayndstomir.com",
    "http://localhost:3000",
    "http://localhost:5173",  # Supports Vite/React local development servers
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3. Initialize Resend Email Engine
resend.api_key = os.environ.get("RESEND_API_KEY")


# ==========================================
#        DATA VALIDATION SCHEMAS
# ==========================================

# Form payload validation schema for client jobs
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

# Form payload validation schema for freelancer onboarding
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

# Haversine Formula for Proximity Routing (Calculates distance in kilometers)
def calculate_proximity(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    rad_lat1, rad_lon1, rad_lat2, rad_lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    
    dlon = rad_lon2 - rad_lon1
    dlat = rad_lat2 - rad_lat1
    a = math.sin(dlat/2)**2 + math.cos(rad_lat1) * math.cos(rad_lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    
    radius_of_earth_km = 6371.0
    return c * radius_of_earth_km


# ==========================================
#             SYSTEM ENDPOINTS
# ==========================================

# Multi-Path Uptime Monitor Health Checks
@app.api_route("", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/health", methods=["GET", "HEAD"], include_in_schema=False)
async def root_health_check():
    return {"status": "healthy", "service": "MindStormerX Core Engine"}


# Route 1: Client Service Booking & Proximity Matching Engine
@app.post("/jobs", status_code=201)
async def create_job(job: JobSubmission):
    # TODO: Connect your production Supabase database instance to pull available technicians dynamically
    
    # Static fallback cluster array for operational execution
    available_technicians = [
        {
            "id": 101,
            "name": "Olamiposi Technical Cluster",
            "email": "viewwhatsappstatus@gmail.com",  
            "phone": "+2348012345678",
            "lat": 6.5244,  
            "lng": 3.3792
        },
        {
            "id": 102,
            "name": "Backup Cluster Representative",
            "email": "backup-tech@mayndstomir.com",
            "phone": "+2348098765432",
            "lat": 6.6018,
            "lng": 3.3515
        }
    ]
    
    # Geospatial Calculation Matrix
    assigned_tech = None
    shortest_distance = float('inf')
    
    for tech in available_technicians:
        distance = calculate_proximity(job.client_lat, job.client_lng, tech["lat"], tech["lng"])
        if distance < shortest_distance:
            shortest_distance = distance
            assigned_tech = tech

    if not assigned_tech:
        raise HTTPException(status_code=404, detail="No localized field technicians available for this category.")

    # Generate external tracking routing links
    live_location_url = f"https://www.google.com/maps/search/?api=1&query={job.client_lat},{job.client_lng}"
    whatsapp_direct_url = f"https://wa.me/{job.phone_number.replace('+', '').replace(' ', '')}"

    try:
        # A. Notification Dispatch to Assigned Field Professional
        resend.Emails.send({
            "from": "MindStormerX Dispatch <alerts@mayndstomir.com>",
            "to": [assigned_tech["email"]],
            "subject": "🚨 Urgent: New Client Assigned in Your Proximity",
            "html": f"""
            <h3>🛠️ Service Request Accepted</h3>
            <p>Hello {assigned_tech["name"]}, you have been assigned a nearby client via proximity matching.</p>
            <hr/>
            <p><strong>Client Name:</strong> {job.full_name}</p>
            <p><strong>Description:</strong> {job.description}</p>
            <p><strong>Scheduled Slot:</strong> {job.preferred_date} at {job.preferred_time}</p>
            <br/>
            <p><strong>📱 Client WhatsApp Link:</strong> <a href="{whatsapp_direct_url}">Chat on WhatsApp ({job.phone_number})</a></p>
            <p><strong>📍 Client Live Location:</strong> <a href="{live_location_url}" target="_blank">Open Navigation Map</a></p>
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
            <p><strong>Assigned Professional:</strong> {assigned_tech["name"]}</p>
            <p><strong>Contact Direct Line:</strong> {assigned_tech["phone"]}</p>
            <br/>
            <p>They are currently reviewing your description details and will connect with you shortly.</p>
            <br/>
            <p>Best regards,<br/>The MindStormerX Team</p>
            """
        })
    except Exception as e:
        print(f"Communications infrastructure email exception: {str(e)}")
        
    return {
        "status": "success", 
        "message": "Application accepted and proximity route assigned.",
        "popup_data": {
            "client_notice": "Application submitted! A field technician has been successfully matched to your location.",
            "technician_notice": f"New client request received. Order assigned to cluster unit: {assigned_tech['name']}.",
            "matched_technician": {
                "name": assigned_tech["name"],
                "phone": assigned_tech["phone"]
            }
        }
    }


# Route 2: Onboarding Endpoint for Freelance Technicians
@app.post("/freelance_applications", status_code=201)
async def register_technician(tech: TechnicianApplication):
    # TODO: Connect your production Supabase table here to store technical applicants
    
    try:
        # Internal Notification email mapping the exact frontend fields
        resend.Emails.send({
            "from": "MindStormerX Core <alerts@mayndstomir.com>",
            "to": ["viewwhatsappstatus@gmail.com"],
            "subject": f"📋 New Technician Applicant: {tech.full_name}",
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
        print(f"Freelancer registration email notification warning: {str(e)}")

    return {
        "status": "success",
        "message": "Application submitted successfully!",
        "popup_data": {
            "technician_notice": "Your application has been received! We will review your details and contact you via WhatsApp shortly."
        }
    }