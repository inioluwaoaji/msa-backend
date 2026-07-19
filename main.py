import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from supabase import create_client, Client
import resend 
import math
from datetime import datetime, timezone

def calculate_distance(lat1, lng1, lat2, lng2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c
CATEGORY_SYNONYMS = {
    "ac": "hvac",
    "air conditioning": "hvac",
    "aircon": "hvac",
    "ac repair": "hvac",
    "plumber": "plumbing",
    "electrician": "electrical",
    "carpenter": "carpentry",
}
 
CATEGORY_DISPLAY_NAMES = {
    "hvac": "HVAC",
    "plumbing": "Plumbing",
    "electrical": "Electrical",
    "painting": "Painting",
    "carpentry": "Carpentry",
    "flooring": "Flooring",
    "appliance_repair": "Appliance Repair",
    "cleaning": "Deep Cleaning",
    "pest_control": "Pest Control",
    "masonry": "Masonry & Tiling",
    "glass_windows": "Glass & Windows",
    "locks_security": "Locks & Security",
    "other": "Other"
}

def get_display_category(raw_value):
    if not raw_value:
        return raw_value
    return CATEGORY_DISPLAY_NAMES.get(raw_value.strip().lower(), raw_value)
def normalize_category(value: str) -> str:
    if not value:
        return ""
    cleaned = value.strip().lower()
    return CATEGORY_SYNONYMS.get(cleaned, cleaned)
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
        "https://maynd-stomir.vercel.app",
        "null"
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

def send_email(to_email: str, subject: str, html_content: str, from_email: str = "customerservice@mayndstomir.com", from_name: str = "MSA Dispatch"):
    if not RESEND_API_KEY:
        print("Resend API key not set — skipping email")
        try:
            supabase.table("email_failures").insert({
                "to_email": to_email,
                "subject": subject,
                "error_message": "Resend API key not set"
            }).execute()
        except Exception:
            pass
        return
    try:
        resend.Emails.send({
            "from": f"{from_name} <{from_email}>",
            "to": to_email,
            "subject": subject,
            "html": html_content
        })
    except Exception as e:
        print(f"Email failed to send: {e}")
        try:
            supabase.table("email_failures").insert({
                "to_email": to_email,
                "subject": subject,
                "error_message": str(e)
            }).execute()
        except Exception:
            pass
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
    trade: List[str]
    experience_years: int
    qid_number: str
    kahramaa_id_url: Optional[str] = None
    id_photo_url: str
    notes: Optional[str] = None
    tech_lat: Optional[float] = None
    tech_lng: Optional[float] = None

@app.get("/")
def read_root():
    return {"status": "healthy", "message": "Maynd Stomir Backend API is running"}

@app.post("/freelance_applications", dependencies=[Depends(verify_api_key)])
@limiter.limit("5/minute")
async def create_application(request: Request, application: FreelanceApplication):
    TRADES_REQUIRING_KAHRAMAA = {"electrical", "plumbing", "hvac"}

    if any(t.lower() in TRADES_REQUIRING_KAHRAMAA for t in application.trade) and not application.kahramaa_id_url:
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
            "description": application.notes,
            "tech_lat": application.tech_lat,
            "tech_lng": application.tech_lng
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

        normalized_category = normalize_category(job.category)
        tech_response = supabase.table("technicians").select("*").execute()
        tech_response.data = [
            t for t in tech_response.data
            if normalized_category in [normalize_category(skill) for skill in (t.get("trade_skill") or [])]
            and t.get("is_approved") is True
            and t.get("is_available") is not False
        ]

        available_technicians = []
        if tech_response.data:
            for candidate in tech_response.data:
                candidate_id = candidate.get("uuid")
                active_jobs = supabase.table("jobs").select("uuid").eq("assigned_technician_id", candidate_id).eq("status", "assigned").execute()
                if not active_jobs.data:
                    available_technicians.append(candidate)

        technician = None
        if available_technicians and job.client_lat and job.client_lng:
            technicians_with_location = [t for t in available_technicians if t.get("tech_lat") and t.get("tech_lng")]
            if technicians_with_location:
                technician = min(
                    technicians_with_location,
                    key=lambda t: calculate_distance(job.client_lat, job.client_lng, t.get("tech_lat"), t.get("tech_lng"))
                )
            else:
                technician = available_technicians[0]
        elif available_technicians:
            technician = available_technicians[0]

        if technician:
            assigned_name = technician.get("full_name")
            assigned_id = technician.get("uuid")

            supabase.table("jobs").update({
                "assigned_technician": assigned_name,
                "assigned_technician_id": assigned_id,
                "status": "assigned"
            }).eq("uuid", job_id).execute()

            supabase.table("technicians").update({
                "is_available": False
            }).eq("uuid", assigned_id).execute()
            job_data["assigned_technician"] = {
                "name": assigned_name,
                "phone": technician.get("phone_number")
            }
            job_data["assigned_technician_id"] = assigned_id
            job_data["status"] = "assigned"

            current_assigned = technician.get("assigned_jobs_count") or 0
            supabase.table("technicians").update({
                "assigned_jobs_count": current_assigned + 1
            }).eq("uuid", assigned_id).execute()

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
                html_content=email_html,
                from_email="career@mayndstomir.com",
                from_name="MSA Careers"
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
        job_data["category"] = get_display_category(job_data.get("category"))
        if job_data.get("assigned_technician_id"):
            tech_lookup = supabase.table("technicians").select("full_name, phone_number").eq("uuid", job_data["assigned_technician_id"]).execute()
            if tech_lookup.data:
                job_data["assigned_technician"] = {
                    "name": tech_lookup.data[0].get("full_name"),
                    "phone": tech_lookup.data[0].get("phone_number")
                }
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
            job["category"] = get_display_category(job.get("category"))
            if job.get("assigned_technician_id"):
                tech_lookup = supabase.table("technicians").select("full_name, phone_number").eq("uuid", job["assigned_technician_id"]).execute()
                if tech_lookup.data:
                    job["assigned_technician"] = {
                        "name": tech_lookup.data[0].get("full_name"),
                        "phone": tech_lookup.data[0].get("phone_number")
                    }
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
        technicians = response.data

        for tech in technicians:
            tech_id = tech.get("uuid")
            approval = tech.get("approval_status") or "pending"

            if approval == "pending":
                tech["status"] = "awaiting_approval"
            elif approval == "rejected":
                tech["status"] = "rejected"
            else:
                active_jobs = supabase.table("jobs").select("uuid").eq("assigned_technician_id", tech_id).eq("status", "assigned").execute()
                tech["status"] = "assigned" if active_jobs.data else "available"

            tech["approval_status"] = approval
            tech["trade_skill"] = [get_display_category(t) for t in (tech.get("trade_skill") or [])]
            tech["assigned_jobs_count"] = tech.get("assigned_jobs_count") or 0
            tech["completed_jobs_count"] = tech.get("completed_jobs_count") or 0

        return {"success": True, "data": technicians}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
class CompleteJobRequest(BaseModel):
    payout_amount: Optional[float] = None

@app.patch("/jobs/{job_id}/complete", dependencies=[Depends(verify_api_key)])
async def complete_job(job_id: int, body: CompleteJobRequest = CompleteJobRequest()):
    try:
        response = supabase.table("jobs").select("*").eq("uuid", job_id).execute()
        if not response.data:
            raise HTTPException(status_code=404, detail="Job not found")

        job = response.data[0]

        supabase.table("jobs").update({
            "status": "completed",
            "payout_amount": body.payout_amount
        }).eq("uuid", job_id).execute()

        technician_id = job.get("assigned_technician_id")
        if technician_id:
            tech_response = supabase.table("technicians").select("completed_jobs_count, assigned_jobs_count, email_address, full_name").eq("uuid", technician_id).execute()
            if tech_response.data:
                technician = tech_response.data[0]
                current_completed = technician.get("completed_jobs_count") or 0
                current_assigned = technician.get("assigned_jobs_count") or 0
                supabase.table("technicians").update({
                    "completed_jobs_count": current_completed + 1,
                    "assigned_jobs_count": max(current_assigned - 1, 0),
                    "is_available": True
                }).eq("uuid", technician_id).execute()

                formatted_job_id = f"#MS-{str(job_id).zfill(4)}"
                completion_timestamp = datetime.now(timezone.utc).strftime("%d %B %Y, %H:%M")
                payout_display = "Pending"

                try:
                    with open("job-completed-email.html", "r", encoding="utf-8") as file:
                        completion_email_html = file.read()

                    completion_email_html = completion_email_html \
                        .replace("{{technician_name}}", technician.get("full_name") or "Partner") \
                        .replace("{{job_id}}", formatted_job_id) \
                        .replace("{{trade_category}}", get_display_category(job.get("category"))) \
                        .replace("{{completion_timestamp}}", completion_timestamp) \
                        .replace("{{payout_amount}}", payout_display)
                except FileNotFoundError:
                    completion_email_html = f"""
                    <h2>Job Completed</h2>
                    <p>Job {formatted_job_id} has been marked as completed. Payout: {payout_display}.</p>
                    """

                send_email(
                    to_email=technician.get("email_address"),
                    subject=f"Job Completed — Receipt {formatted_job_id}",
                    html_content=completion_email_html,
                    from_email="career@mayndstomir.com",
                    from_name="MSA Careers"
                )

        client_completion_email_html = f"""
        <h2>Your Request Has Been Completed</h2>
        <p>Hi {job.get('customer_name')},</p>
        <p>Your maintenance request for <strong>{job.get('category')}</strong> has been marked as completed. Thank you for using Maynd Stomir!</p>
        """

        send_email(
            to_email=job.get("email"),
            subject="Your Maintenance Request Has Been Completed",
            html_content=client_completion_email_html
        )

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

        supabase.table("technicians").update({
            "is_available": False
        }).eq("uuid", body.technician_id).execute()

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
            html_content=email_html,
            from_email="career@mayndstomir.com",
            from_name="MSA Careers"
        )
        return {"success": True, "message": f"Job {job_id} reassigned to {assigned_name}"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/email_failures", dependencies=[Depends(verify_api_key)])
async def get_email_failures():
    try:
        response = supabase.table("email_failures").select("*").order("created_at", desc=True).execute()
        return {"success": True, "data": response.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/jobs/{job_id}/cancel", dependencies=[Depends(verify_api_key)])
async def cancel_job(job_id: int):
    try:
        response = supabase.table("jobs").select("*").eq("uuid", job_id).execute()
        if not response.data:
            raise HTTPException(status_code=404, detail="Job not found")

        job = response.data[0]

        if job.get("status") == "completed":
            raise HTTPException(status_code=400, detail="Cannot cancel a completed job")
        if job.get("status") == "cancelled":
            raise HTTPException(status_code=400, detail="Job is already cancelled")

        created_at_str = job.get("created_at")
        created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        hours_passed = (now - created_at).total_seconds() / 3600

        if hours_passed > 2:
            raise HTTPException(status_code=400, detail="Cancellation window has expired (2 hours)")

        supabase.table("jobs").update({"status": "cancelled"}).eq("uuid", job_id).execute()

        technician_id = job.get("assigned_technician_id")
        if technician_id:
            tech_response = supabase.table("technicians").select("assigned_jobs_count").eq("uuid", technician_id).execute()
            if tech_response.data:
                current_assigned = tech_response.data[0].get("assigned_jobs_count") or 0
                supabase.table("technicians").update({
                    "assigned_jobs_count": max(current_assigned - 1, 0),
                    "is_available": True
                }).eq("uuid", technician_id).execute()

        cancellation_email_html = f"""
        <h2>Your Request Has Been Cancelled</h2>
        <p>Hi {job.get('customer_name')},</p>
        <p>Your maintenance request for <strong>{job.get('category')}</strong> has been successfully cancelled as requested.</p>
        <p><strong>Description:</strong> {job.get('description')}</p>
        """

        send_email(
            to_email=job.get("email"),
            subject="Your Maintenance Request Has Been Cancelled",
            html_content=cancellation_email_html
        )

        send_email(
            to_email="customerservice@mayndstomir.com",
            subject="A Job Was Cancelled",
            html_content=cancellation_email_html
        )

        return {"success": True, "message": "Job cancelled successfully"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
class ApprovalUpdate(BaseModel):
    approval_status: str  # "approved" or "rejected"

@app.patch("/workers/{worker_id}/approve", dependencies=[Depends(verify_api_key)])
async def update_technician_approval(worker_id: int, body: ApprovalUpdate):
    try:
        if body.approval_status not in ["approved", "rejected"]:
            raise HTTPException(status_code=400, detail="approval_status must be 'approved' or 'rejected'")

        response = supabase.table("technicians").select("*").eq("uuid", worker_id).execute()
        if not response.data:
            raise HTTPException(status_code=404, detail="Technician not found")

        technician = response.data[0]
        is_approved_bool = body.approval_status == "approved"

        supabase.table("technicians").update({
            "approval_status": body.approval_status,
            "is_approved": is_approved_bool
        }).eq("uuid", worker_id).execute()

        if is_approved_bool:
            approval_email_html = f"""
            <p>Hi {technician.get('full_name')},</p>
            <p>Your application and credentials have been officially verified. Welcome to the Maynd Stomir network.</p>
            <p>Your profile is now live, and you are fully eligible to receive building maintenance assignments across Doha.</p>
            <h3>How Your Assignments Work</h3>
            <p>We operate a fully automated, GPS-based dispatch system. To keep things seamless, you do not need to log into a dashboard or manually search for work.</p>
            <p><strong>Automatic Matching:</strong> When a client request matches your verified trade skills and geographic location, you will receive an immediate email alert containing the full job details.</p>
            <p><strong>Availability Management:</strong> Once you are assigned a job, our system automatically flags you as "busy" so you will not be double-booked. The moment the client's job is marked completed, you are instantly placed back into the available matching pool.</p>
            <p><strong>Job History & Payments:</strong> For every completed assignment, you will receive an automated digital receipt to this email address detailing your exact payout amount. Please retain these emails as your official financial ledger.</p>
            <p>If you ever need to update your contact details or have any operational questions, our partner support team is available at career@mayndstomir.com.</p>
            <p>We are excited to have your expertise on board.</p>
            <p>Best regards,<br>The Maynd Stomir Team</p>
            """
            send_email(
                to_email=technician.get("email_address"),
                subject="Welcome to Maynd Stomir — Your Partner Account is Active",
                html_content=approval_email_html,
                from_email="career@mayndstomir.com",
                from_name="MSA Careers"
            )
        else:
            rejection_email_html = f"""
            <h2>Application Update</h2>
            <p>Hi {technician.get('full_name')},</p>
            <p>Thank you for your interest in joining Maynd Stomir. After reviewing your application, we're unable to move forward at this time.</p>
            """
            send_email(
                to_email=technician.get("email_address"),
                subject="Update on Your Application",
                html_content=rejection_email_html,
                from_email="career@mayndstomir.com",
                from_name="MSA Careers"
            )

        return {"success": True, "message": f"Technician approval status set to {body.approval_status}"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))