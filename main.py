import os
import math
import resend
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional

# 1. Initialize FastAPI Application
app = FastAPI(title="MindStormerX Proximity Match API")

# 2. Initialize Resend Email Engine
resend.api_key = os.environ.get("RESEND_API_KEY")

# 3. Data Schemas for Payload Validation
class JobSubmission(BaseModel):
    full_name: str
    email: str
    phone_number: str  # Client's WhatsApp number
    category: str
    description: str
    preferred_date: str
    preferred_time: str
    # Live coordinates passed from the frontend map interface
    client_lat: float  
    client_lng: float  

# 4. Haversine Formula for Proximity Routing (Calculates distance in kilometers)
def calculate_proximity(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    # Convert decimal degrees to radians 
    rad_lat1, rad_lon1, rad_lat2, rad_lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    
    # Haversine core formula
    dlon = rad_lon2 - rad_lon1
    dlat = rad_lat2 - rad_lat1
    a = math.sin(dlat/2)**2 + math.cos(rad_lat1) * math.cos(rad_lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    
    radius_of_earth_km = 6371.0
    return c * radius_of_earth_km

# 5. Bulletproof Uptime Monitor Routes
@app.api_route("", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/health", methods=["GET", "HEAD"], include_in_schema=False)
async def root_health_check():
    return {"status": "healthy", "service": "MindStormerX Backend"}

# 6. Intelligent Proximity Matching and Dispatch Route
@app.post("/jobs", status_code=201)
async def create_job(job: JobSubmission):
    
    # --- STEP A: DATABASE QUERY (PLACEHOLDER FOR SUPABASE/POSTGRES) ---
    # Fetch active technicians filtering by matching job.category.
    # Each technician row needs: id, name, email, phone, current_lat, current_lng
    
    # Mocking technician cluster data for runtime execution:
    available_technicians = [
        {
            "id": 101,
            "name": "Olamiposi Technical Cluster",
            "email": "viewwhatsappstatus@gmail.com",  # Using verified email for testing stability
            "phone": "+2348012345678",
            "lat": 6.5244,  # Example coordinates
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
    
    # --- STEP B: PROXIMITY SORTING LOGIC ---
    assigned_tech = None
    shortest_distance = float('inf')
    
    for tech in available_technicians:
        distance = calculate_proximity(job.client_lat, job.client_lng, tech["lat"], tech["lng"])
        if distance < shortest_distance:
            shortest_distance = distance
            assigned_tech = tech

    if not assigned_tech:
        raise HTTPException(status_code=404, detail="No localized field technicians available for this category.")

    # --- STEP C: PERSIST DATA ---
    # TODO: Write job execution record and assignment mapping to Supabase
    # supabase.table("jobs").insert({"client": job.full_name, "assigned_tech_id": assigned_tech["id"], ...})

    # --- STEP D: LIVE MAP ROUTING URLS ---
    # Generates a universal clickable link for the technician to route to the client
    live_location_url = f"https://www.google.com/maps/search/?api=1&query={job.client_lat},{job.client_lng}"
    # Formats a clean direct click-to-chat hyperlink for WhatsApp
    whatsapp_direct_url = f"https://wa.me/{job.phone_number.replace('+', '')}"

    # --- STEP E: NOTIFICATION ENGINE DISPATCHES ---
    try:
        # 1. Alert Dispatch to the Assigned Technician
        resend.Emails.send({
            "from": "MindStormerX Dispatch <alerts@mayndstomir.com>",
            "to": [assigned_tech["email"]],
            "subject": "🚨 Urgent: New Client Assigned in Your Proximity",
            "html": f"""
            <h3>🛠️ Service Request Accepted</h3>
            <p>Hello {assigned_tech["name"]}, you have been assigned a nearby client based on coordinate matching.</p>
            <hr/>
            <p><strong>Client Name:</strong> {job.full_name}</p>
            <p><strong>Description:</strong> {job.description}</p>
            <p><strong>Scheduled Window:</strong> {job.preferred_date} at {job.preferred_time}</p>
            <br/>
            <p><strong>📱 Client WhatsApp Link:</strong> <a href="{whatsapp_direct_url}">Chat on WhatsApp ({job.phone_number})</a></p>
            <p><strong>📍 Client Live Location:</strong> <a href="{live_location_url}" target="_blank">Open Navigation Map</a></p>
            """
        })
        
        # 2. Confirmation Dispatch to the Client
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
        print(f"Communications infrastructure exception: {str(e)}")
        
    # --- STEP F: FRONTEND POPUP METADATA ---
    # Returning this structured object allows your web/mobile frontend to read the data
    # and immediately pop up success modals on both screens.
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