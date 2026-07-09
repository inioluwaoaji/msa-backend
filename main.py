import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from supabase import create_client, Client
import resend 
from fastapi import Request
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

app = FastAPI(title="Maynd Stomir Backend API")

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://mayndstomir.com",
        "https://www.mayndstomir.com",
        "https://maynd-stomir.vercel.app"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_KEY environment variables.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY

def send_email(to_email: str, subject: str, html_content: str):
    if not RESEND_API_KEY:
        print("Resend API key not set — skipping email")
        return
    try:
        resend.Emails.send({
            "from": "MSA Dispatch <customerservice@mayndstomir.com>",
            "to": to_email,
            "subject": subject,
            "html": html_content
        })
    except Exception as e:
        print(f"Email failed to send: {e}")
from fastapi import Header, Depends

API_KEY = os.environ.get("API_KEY")

def verify_api_key(x_api_key: str = Header(None)):
    if not API_KEY:
        raise HTTPException(status_code=500, detail="Server API key not configured")
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
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

@app.post("/freelance_applications", dependencies=[Depends(verify_api_key)])
@limiter.limit("5/minute")
async def create_application(request: Request, application: FreelanceApplication):
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

@app.post("/jobs", dependencies=[Depends(verify_api_key)])
@limiter.limit("5/minute")
async def create_job(request: Request, job: MaintenanceRequest):
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
            "status": "pending",
            "client_lat": job.client_lat,
            "client_lng": job.client_lng
        }

        response = supabase.table("jobs").insert(data).execute()
        job_data = response.data[0]
        job_id = job_data["uuid"]

        tech_response = supabase.table("technicians").select("*").ilike("trade_skill", job.category).execute()

        technician = None
        if tech_response.data:
            for candidate in tech_response.data:
                candidate_id = candidate.get("uuid")
                active_jobs = supabase.table("jobs").select("uuid").eq("assigned_technician_id", candidate_id).eq("status", "assigned").execute()
                if not active_jobs.data:
                    technician = candidate
                    break

        if technician:
            assigned_name = technician.get("full_name")
            assigned_id = technician.get("uuid")

            supabase.table("jobs").update({
                "assigned_technician": assigned_name,
                "assigned_technician_id": assigned_id,
                "status": "assigned"
            }).eq("uuid", job_id).execute()
            job_data["assigned_technician"] = assigned_name
            job_data["assigned_technician_id"] = assigned_id
            job_data["status"] = "assigned"

            maps_link = ""
            if job.client_lat and job.client_lng:
                maps_link = f"https://www.google.com/maps?q={job.client_lat},{job.client_lng}"

            email_html = f"""
            <h2>New {job.category.upper()} Job Assigned</h2>
            <p><strong>Problem:</strong> {job.description}</p>
            <p><strong>Client Phone:</strong> {job.phone_number}</p>
            {'<p><strong>Live Location:</strong> <a href="' + maps_link + '">View on Map</a></p>' if maps_link else ''}
            """

            send_email(
                to_email=technician.get("email_address"),
                subject=f"New {job.category.upper()} Job - Action Needed",
                html_content=email_html
            )

        client_email_html = f"""
        <h2>Your Request Has Been Assigned</h2>
        <p>Hi {job.full_name},</p>
        <p>Your maintenance request for <strong>{job.category}</strong> has been assigned to a technician who will contact you shortly.</p>
        <p><strong>Description:</strong> {job.description}</p>
        """

        send_email(
            to_email=job.email,
            subject="Your Maintenance Request Has Been Assigned",
            html_content=client_email_html
        )

        job_data["id"] = job_data.pop("uuid")
        return {"success": True, "data": [job_data]}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@app.get("/jobs/{job_id}", dependencies=[Depends(verify_api_key)])
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
@app.get("/jobs", dependencies=[Depends(verify_api_key)])
async def get_all_jobs():
    try:
        response = supabase.table("jobs").select("*").execute()
        jobs = response.data
        for job in jobs:
            job["id"] = job.pop("uuid")
        return {"success": True, "data": jobs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/jobs/lookup/{phone_number}", dependencies=[Depends(verify_api_key)])
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

@app.get("/workers", dependencies=[Depends(verify_api_key)])
async def get_all_technicians():
    try:
        response = supabase.table("technicians").select("*").execute()
        return {"success": True, "data": response.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@app.patch("/jobs/{job_id}/complete", dependencies=[Depends(verify_api_key)])
async def complete_job(job_id: int):
    try:
        response = supabase.table("jobs").select("*").eq("uuid", job_id).execute()
        if not response.data:
            raise HTTPException(status_code=404, detail="Job not found")

        job = response.data[0]

        supabase.table("jobs").update({"status": "completed"}).eq("uuid", job_id).execute()

        technician_id = job.get("assigned_technician_id")
        if technician_id:
            tech_response = supabase.table("technicians").select("completed_jobs_count").eq("uuid", technician_id).execute()
            if tech_response.data:
                current_count = tech_response.data[0].get("completed_jobs_count") or 0
                supabase.table("technicians").update({
                    "completed_jobs_count": current_count + 1
                }).eq("uuid", technician_id).execute()

        return {"success": True, "message": "Job marked as completed"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
class ReassignRequest(BaseModel):
    technician_id: int

@app.patch("/jobs/{job_id}/reassign", dependencies=[Depends(verify_api_key)])
async def reassign_job(job_id: int, body: ReassignRequest):
    try:
        job_response = supabase.table("jobs").select("*").eq("uuid", job_id).execute()
        if not job_response.data:
            raise HTTPException(status_code=404, detail="Job not found")

        tech_response = supabase.table("technicians").select("*").eq("uuid", body.technician_id).execute()
        if not tech_response.data:
            raise HTTPException(status_code=404, detail="Technician not found")

        job = job_response.data[0]
        technician = tech_response.data[0]
        assigned_name = technician.get("full_name")

        supabase.table("jobs").update({
            "assigned_technician": assigned_name,
            "assigned_technician_id": body.technician_id,
            "status": "assigned"
        }).eq("uuid", job_id).execute()

        maps_link = ""
        if job.get("client_lat") and job.get("client_lng"):
            maps_link = f"https://www.google.com/maps?q={job['client_lat']},{job['client_lng']}"

        email_html = f"""
        <h2>Job Reassigned To You</h2>
        <p><strong>Problem:</strong> {job.get('description')}</p>
        <p><strong>Client Phone:</strong> {job.get('phone_number')}</p>
        {'<p><strong>Live Location:</strong> <a href="' + maps_link + '">View on Map</a></p>' if maps_link else ''}
        """

        send_email(
            to_email=technician.get("email_address"),
            subject=f"Job Reassigned To You - Action Needed",
            html_content=email_html
        )

        return {"success": True, "message": f"Job {job_id} reassigned to {assigned_name}"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))