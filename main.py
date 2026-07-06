import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from supabase import create_client, Client
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
app = FastAPI(title="Maynd Stomir Backend API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_KEY environment variables.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
ZOHO_EMAIL = os.environ.get("ZOHO_EMAIL")
ZOHO_APP_PASSWORD = os.environ.get("ZOHO_APP_PASSWORD")

def send_technician_email(to_email: str, subject: str, html_content: str):
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = ZOHO_EMAIL
        msg["To"] = to_email
        msg.attach(MIMEText(html_content, "html"))

        with smtplib.SMTP("smtp.zoho.com", 587) as server:
            server.starttls()
            server.login(ZOHO_EMAIL, ZOHO_APP_PASSWORD)
            server.sendmail(ZOHO_EMAIL, to_email, msg.as_string())
    except Exception as e:
        print(f"Email failed to send: {e}")
# Matches Olamiposi's payload fields exactly
class FreelanceApplication(BaseModel):
    full_name: str
    email: str
    phone_number: str
    trade: str  
    experience_years: int
    qid_number: str
    kahramaa_id_url: Optional[str] = None
    id_photo_url: str
    notes: Optional[str] = None

@app.get("/")
def read_root():
    return {"status": "healthy", "message": "Maynd Stomir Backend API is running"}

@app.post("/freelance_applications")
async def create_application(application: FreelanceApplication):
    TRADES_REQUIRING_KAHRAMAA = {"electrical", "plumbing", "hvac"}

    if application.trade.lower() in TRADES_REQUIRING_KAHRAMAA and not application.kahramaa_id_url:
        raise HTTPException(
            status_code=422,
            detail=f"kahramaa_id_url is required for the trade: {application.trade}"
        )

    try:
        data = {
            "full_name": application.full_name,
            "email_address": application.email,
            "phone_number": application.phone_number,
            "trade_skill": application.trade,
            "experience_years": application.experience_years,
            "qid_number": application.qid_number,
            "kahramaa_id_url": application.kahramaa_id_url,
            "id_photo_url": application.id_photo_url,
            "description": application.notes
        }

        # Pointing to the verified technicians table
        response = supabase.table("technicians").insert(data).execute()
        return {"success": True, "data": response.data}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
class MaintenanceRequest(BaseModel):
    full_name: str
    phone_number: str
    category: str
    client_lat: Optional[float] = None
    client_lng: Optional[float] = None
    description: str
    email: str
    job_photo_url: Optional[str] = None
    preferred_date: str
    preferred_time: str

@app.post("/jobs")
async def create_job(job: MaintenanceRequest):
    try:
        combined_datetime = f"{job.preferred_date}T{job.preferred_time}:00"

        data = {
            "customer_name": job.full_name,
            "phone_number": job.phone_number,
            "category": job.category,
            "description": job.description,
            "email": job.email,
            "photo_url": job.job_photo_url,
            "customer_availability": combined_datetime,
            "status": "pending"
        }

        response = supabase.table("jobs").insert(data).execute()
        job_data = response.data[0]
        job_id = job_data["uuid"]

        tech_response = supabase.table("technicians").select("*").ilike("trade_skill", job.category).execute()

        if tech_response.data:
            technician = tech_response.data[0]
            assigned_name = technician.get("full_name")

            supabase.table("jobs").update({"assigned_technician": assigned_name}).eq("uuid", job_id).execute()
            job_data["assigned_technician"] = assigned_name

            maps_link = ""
            if job.client_lat and job.client_lng:
                maps_link = f"https://www.google.com/maps?q={job.client_lat},{job.client_lng}"

            email_html = f"""
            <h2>New {job.category.upper()} Job Assigned</h2>
            <p><strong>Problem:</strong> {job.description}</p>
            <p><strong>Client Phone:</strong> {job.phone_number}</p>
            {'<p><strong>Live Location:</strong> <a href="' + maps_link + '">View on Map</a></p>' if maps_link else ''}
            """

            if ZOHO_EMAIL and ZOHO_APP_PASSWORD:
                send_technician_email(
                    to_email=technician.get("email_address"),
                    subject=f"New {job.category.upper()} Job - Action Needed",
                    html_content=email_html
                )

        job_data["id"] = job_data.pop("uuid")
        return {"success": True, "data": [job_data]}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@app.get("/jobs/{job_id}")
async def get_job(job_id: int):
    try:
        response = supabase.table("jobs").select("*").eq("uuid", job_id).execute()
        if not response.data:
            raise HTTPException(status_code=404, detail="Job not found")
        job_data = response.data[0]
        job_data["id"] = job_data.pop("uuid")
        return {"success": True, "data": job_data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@app.get("/jobs")
async def get_all_jobs():
    try:
        response = supabase.table("jobs").select("*").execute()
        jobs = response.data
        for job in jobs:
            job["id"] = job.pop("uuid")
        return {"success": True, "data": jobs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/jobs/lookup/{phone_number}")
async def lookup_jobs_by_phone(phone_number: str):
    try:
        normalized = phone_number.strip().replace(" ", "").replace("-", "")
        response = supabase.table("jobs").select("*").execute()
        matches = [
            j for j in response.data
            if j.get("phone_number", "").strip().replace(" ", "").replace("-", "").endswith(normalized[-8:])
        ]
        for job in matches:
            job["id"] = job.pop("uuid")
        if not matches:
            raise HTTPException(status_code=404, detail="No jobs found for this phone number")
        return {"success": True, "data": matches}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/workers")
async def get_all_technicians():
    try:
        response = supabase.table("technicians").select("*").execute()
        return {"success": True, "data": response.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))