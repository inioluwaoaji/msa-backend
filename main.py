import os
from fastapi import FastAPI, HTTPException, Request, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from supabase import create_client, Client
import resend
import math
from datetime import datetime, timezone, timedelta
import hmac
import hashlib
import base64
import httpx
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

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

ACTIVE_JOB_STATUSES = ["dispatched", "in_diagnostics", "awaiting_payment", "paid"]

def get_display_category(raw_value):
    if not raw_value:
        return raw_value
    return CATEGORY_DISPLAY_NAMES.get(raw_value.strip().lower(), raw_value)

def normalize_category(value: str) -> str:
    if not value:
        return ""
    cleaned = value.strip().lower()
    return CATEGORY_SYNONYMS.get(cleaned, cleaned)

def find_available_technician(
    category: str,
    client_lat: Optional[float],
    client_lng: Optional[float],
    exclude_technician_id: Optional[str] = None,
    lock: bool = True
):
    normalized_category = normalize_category(category)
    tech_response = supabase.table("technicians").select("*").execute()
    tech_response.data = [
        t for t in tech_response.data
        if normalized_category in [normalize_category(skill) for skill in (t.get("trade_skill") or [])]
        and t.get("is_approved") is True
        and t.get("is_available") is not False
        and t.get("uuid") != exclude_technician_id
    ]

    cooldown_cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    available_technicians = []
    for candidate in tech_response.data:
        candidate_id = candidate.get("uuid")
        active_jobs = supabase.table("jobs").select("uuid").eq("assigned_technician_id", candidate_id).in_("status", ACTIVE_JOB_STATUSES).execute()
        if active_jobs.data:
            continue

        recent_rejections = supabase.table("technician_rejections").select("id").eq("technician_id", candidate_id).gte("created_at", cooldown_cutoff).execute()
        if recent_rejections.data and len(recent_rejections.data) >= 3:
            continue

        available_technicians.append(candidate)

    if client_lat and client_lng:
        technicians_with_location = [t for t in available_technicians if t.get("tech_lat") and t.get("tech_lng")]
        if technicians_with_location:
            available_technicians = sorted(
                technicians_with_location,
                key=lambda t: calculate_distance(client_lat, client_lng, t.get("tech_lat"), t.get("tech_lng"))
            )

    for candidate in available_technicians:
        candidate_id = candidate.get("uuid")

        if lock:
            claim_result = supabase.table("technicians").update({
                "is_available": False
            }).eq("uuid", candidate_id).eq("is_available", True).execute()

            if claim_result.data:
                return candidate
        else:
            return candidate

    return None

SKIPCASH_CLIENT_ID = os.environ.get("SKIPCASH_CLIENT_ID")
SKIPCASH_KEY_ID = os.environ.get("SKIPCASH_KEY_ID")
SKIPCASH_SECRET_KEY = os.environ.get("SKIPCASH_SECRET_KEY")
SKIPCASH_WEBHOOK_KEY = os.environ.get("SKIPCASH_WEBHOOK_KEY")
SKIPCASH_API_URL = os.environ.get("SKIPCASH_API_URL")

def compute_skipcash_signature(combined_string: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), combined_string.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")

def generate_payment_link(job_id: int, amount: float, tracking_token: str, customer_name: str, phone_number: str, email: str) -> Optional[str]:
    name_parts = (customer_name or "Customer").strip().split(" ", 1)
    first_name = name_parts[0]
    last_name = name_parts[1] if len(name_parts) > 1 else "N/A"
    amount_str = f"{amount:.2f}"

    payment_details = {
        "Uid": SKIPCASH_CLIENT_ID,
        "KeyId": SKIPCASH_KEY_ID,
        "Amount": amount_str,
        "FirstName": first_name,
        "LastName": last_name,
        "Phone": phone_number,
        "Email": email,
        "TransactionId": tracking_token,
    }

    combined_data = (
        f"Uid={payment_details['Uid']},KeyId={payment_details['KeyId']},"
        f"Amount={payment_details['Amount']},FirstName={payment_details['FirstName']},"
        f"LastName={payment_details['LastName']},Phone={payment_details['Phone']},"
        f"Email={payment_details['Email']},TransactionId={payment_details['TransactionId']}"
    )

    signature = compute_skipcash_signature(combined_data, SKIPCASH_SECRET_KEY)

    try:
        response = httpx.post(
            f"{SKIPCASH_API_URL}/api/v1/payments",
            json=payment_details,
            headers={"Authorization": signature},
            timeout=15
        )
        response_data = response.json()
        print(f"SkipCash payment creation response: {response_data}")

        payment_url = response_data.get("PaymentUrl") or response_data.get("paymentUrl") or response_data.get("Url")
        if not payment_url:
            print("SkipCash response missing recognizable payment URL field — check the logged response above and adjust the field name.")
        return payment_url

    except Exception as e:
        print(f"SkipCash payment creation failed: {e}")
        return None

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

API_KEY = os.environ.get("API_KEY")

def verify_api_key(x_api_key: str = Header(None)):
    if not API_KEY:
        raise HTTPException(status_code=500, detail="Server API key not configured")
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
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

@app.head("/")
def read_root_head():
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
    zone_number: Optional[str] = None
    street_number: Optional[str] = None
    building_number: Optional[str] = None
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
            "zone_number": job.zone_number,
            "street_number": job.street_number,
            "building_number": job.building_number,
            "description": job.description,
            "email": job.email,
            "photo_url": job.job_photo_url,
            "customer_availability": combined_datetime,
            "status": "pending_dispatch",
            "client_lat": job.client_lat,
            "client_lng": job.client_lng
        }

        response = supabase.table("jobs").insert(data).execute()
        job_data = response.data[0]
        job_id = job_data["uuid"]
        tracking_token = job_data.get("tracking_token")
        tracking_url = f"https://www.mayndstomir.com/status?id={tracking_token}" if tracking_token else ""

        # Find candidate WITHOUT locking
        technician = find_available_technician(
            job.category,
            job.client_lat,
            job.client_lng,
            lock=False
        )

        if technician:
            assigned_name = technician.get("full_name")
            assigned_id = technician.get("uuid")

            supabase.table("jobs").update({
                "assigned_technician": assigned_name,
                "assigned_technician_id": assigned_id,
                "status": "dispatched"
            }).eq("uuid", job_id).execute()

            job_data["assigned_technician"] = {
                "name": assigned_name,
                "phone": technician.get("phone_number")
            }
            job_data["assigned_technician_id"] = assigned_id
            job_data["status"] = "dispatched"

            job_manage_url = f"https://www.mayndstomir.com/job-manage.html?id={tracking_token}"

            maps_link = ""
            if job.client_lat and job.client_lng:
                maps_link = f"https://www.google.com/maps?q={job.client_lat},{job.client_lng}"

            email_html = f"""
            <h2>New Job Invitation — {get_display_category(job.category)}</h2>
            <p><strong>Problem:</strong> {job.description}</p>
            <p><strong>Client Phone:</strong> {job.phone_number}</p>
            {'<p><strong>Location:</strong> <a href="' + maps_link + '">View on Map</a></p>' if maps_link else ''}
            <p style="margin-top:20px;">
                <a href="{job_manage_url}" 
                   style="background:#2563eb;color:white;padding:12px 24px;text-decoration:none;border-radius:6px;font-weight:bold;">
                   Accept or Decline Job
                </a>
            </p>
            <p style="font-size:12px;color:#666;">Or copy this link: {job_manage_url}</p>
            """

            send_email(
                to_email=technician.get("email_address"),
                subject=f"New {get_display_category(job.category)} Job Invitation",
                html_content=email_html,
                from_email="career@mayndstomir.com",
                from_name="MSA Careers"
            )

        client_email_html = f"""
        <h2>Request Received — Matching Your Technician</h2>
        <p>Hi {job.full_name},</p>
        <p>We've received your maintenance request for <strong>{get_display_category(job.category)}</strong> and are matching you with the nearest available technician.</p>
        <p><strong>Description:</strong> {job.description}</p>
        {'<p><a href="' + tracking_url + '">Track your request status here</a></p>' if tracking_url else ''}
        """

        send_email(
            to_email=job.email,
            subject="Request Received — Matching Your Technician",
            html_content=client_email_html
        )

        job_data["id"] = job_data.pop("uuid")
        return {"success": True, "data": [job_data]}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
class GeocodeRequest(BaseModel):
    query: str

@app.post("/geocode/places-textsearch")
@limiter.limit("10/minute")
async def geocode_places_textsearch(request: Request, body: GeocodeRequest):
    google_api_key = os.environ.get("GOOGLE_API_KEY")
    if not google_api_key:
        raise HTTPException(status_code=500, detail="GOOGLE_API_KEY is not configured on the server")

    if not body.query or not body.query.strip():
        raise HTTPException(status_code=400, detail="query is required")

    import urllib.parse
    import httpx

    encoded_query = urllib.parse.quote(body.query.strip())
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={encoded_query}&key={google_api_key}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            data = response.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to reach Google Geocoding API: {str(e)}")

    if data.get("status") != "OK" or not data.get("results"):
        raise HTTPException(
            status_code=404,
            detail=f"No results found for query. Google status: {data.get('status')}"
        )

    result = data["results"][0]
    location = result["geometry"]["location"]

    return {
        "formatted_address": result.get("formatted_address"),
        "lat": location.get("lat"),
        "lng": location.get("lng")
    }
@app.get("/jobs/{job_id}", dependencies=[Depends(verify_api_key)])
async def get_job(job_id: str):
    try:
        if job_id.isdigit():
            raise HTTPException(status_code=400, detail="Numeric job IDs are not accepted. Use the tracking token instead.")

        response = supabase.table("jobs").select("*").eq("tracking_token", job_id).execute()

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
                active_jobs = supabase.table("jobs").select("uuid").eq("assigned_technician_id", tech_id).in_("status", ACTIVE_JOB_STATUSES).execute()
                tech["status"] = "assigned" if active_jobs.data else "available"

            tech["approval_status"] = approval
            tech["trade_skill"] = [get_display_category(t) for t in (tech.get("trade_skill") or [])]
            tech["assigned_jobs_count"] = tech.get("assigned_jobs_count") or 0
            tech["completed_jobs_count"] = tech.get("completed_jobs_count") or 0

        return {"success": True, "data": technicians}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
def finalize_job_completion(job: dict, internal_job_id: int):
    technician_id = job.get("assigned_technician_id")
    formatted_job_id = f"#MS-{str(internal_job_id).zfill(4)}"
    completion_timestamp = datetime.now(timezone.utc).strftime("%d %B %Y, %H:%M")
    payout_amount = job.get("total_amount")

    if technician_id:
        tech_response = supabase.table("technicians").select("completed_jobs_count, assigned_jobs_count, email_address, full_name, is_approved, trade_skill, tech_lat, tech_lng").eq("uuid", technician_id).execute()
        if tech_response.data:
            technician = tech_response.data[0]
            current_completed = technician.get("completed_jobs_count") or 0
            current_assigned = technician.get("assigned_jobs_count") or 0
            supabase.table("technicians").update({
                "completed_jobs_count": current_completed + 1,
                "assigned_jobs_count": max(current_assigned - 1, 0),
                "is_available": True
            }).eq("uuid", technician_id).execute()

            if payout_amount:
                supabase.table("partner_payouts").insert({
                    "technician_id": technician_id,
                    "job_id": internal_job_id,
                    "amount": payout_amount
                }).execute()

            if technician.get("is_approved") is True:
                payout_display = f"{payout_amount:.2f}" if payout_amount else "Pending"

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

            assign_queued_job_to_technician(technician_id, technician)

    receipt_amount = f"QAR {job.get('total_amount'):.2f}" if job.get('total_amount') else "N/A"

    client_completion_email_html = f"""
    <h2>Job Finalized — Thank You!</h2>
    <p>Hi {job.get('customer_name')},</p>
    <p>Your maintenance request for <strong>{job.get('category')}</strong> has been finalized. Thank you for using Maynd Stomir!</p>
    <p><strong>Total Paid:</strong> {receipt_amount}</p>
    """

    send_email(
        to_email=job.get("email"),
        subject="Job Finalized — Thank You!",
        html_content=client_completion_email_html
    )


def assign_queued_job_to_technician(technician_id: int, technician: dict):
    matching_queued = supabase.table("jobs").select("*").eq("status", "pending_dispatch").execute()
    candidates = [
        j for j in matching_queued.data
        if normalize_category(j.get("category")) in [normalize_category(skill) for skill in (technician.get("trade_skill") or [])]
    ]
    if not candidates:
        return

    oldest_queued = sorted(candidates, key=lambda j: j.get("created_at"))[0]
    queued_job_id = oldest_queued.get("uuid")

    claim_result = supabase.table("technicians").update({
        "is_available": False
    }).eq("uuid", technician_id).eq("is_available", True).execute()

    if not claim_result.data:
        return

    supabase.table("jobs").update({
        "assigned_technician": technician.get("full_name"),
        "assigned_technician_id": technician_id,
        "status": "dispatched"
    }).eq("uuid", queued_job_id).execute()

    current_assigned = technician.get("assigned_jobs_count") or 0
    supabase.table("technicians").update({
        "assigned_jobs_count": current_assigned + 1
    }).eq("uuid", technician_id).execute()

    maps_link = ""
    if oldest_queued.get("client_lat") and oldest_queued.get("client_lng"):
        maps_link = f"https://www.google.com/maps?q={oldest_queued['client_lat']},{oldest_queued['client_lng']}"

    email_html = f"""
    <h2>New {get_display_category(oldest_queued.get('category')).upper()} Job Assigned</h2>
    <p><strong>Problem:</strong> {oldest_queued.get('description')}</p>
    <p><strong>Client Phone:</strong> {oldest_queued.get('phone_number')}</p>
    {'<p><strong>Live Location:</strong> <a href="' + maps_link + '">View on Map</a></p>' if maps_link else ''}
    """

    send_email(
        to_email=technician.get("email_address"),
        subject=f"New {get_display_category(oldest_queued.get('category')).upper()} Job - Action Needed",
        html_content=email_html,
        from_email="career@mayndstomir.com",
        from_name="MSA Careers"
    )


class CompleteJobRequest(BaseModel):
    completed_by: str  # "technician" or "client"

@app.patch("/jobs/{job_id}/complete", dependencies=[Depends(verify_api_key)])
async def complete_job(job_id: str, body: CompleteJobRequest):
    try:
        if body.completed_by not in ["technician", "client"]:
            raise HTTPException(status_code=400, detail="completed_by must be 'technician' or 'client'")

        response = supabase.table("jobs").select("*").eq("tracking_token", job_id).execute()
        if not response.data:
            raise HTTPException(status_code=404, detail="Job not found")

        job = response.data[0]
        internal_job_id = job.get("uuid")

        if job.get("status") not in ["paid", "pending_completion"]:
            raise HTTPException(status_code=400, detail=f"Job cannot be completed from status '{job.get('status')}'")

        now = datetime.now(timezone.utc).isoformat()
        update_fields = {}

        if body.completed_by == "technician":
            update_fields["tech_completed"] = True
            update_fields["tech_completed_at"] = now
        else:
            update_fields["client_completed"] = True
            update_fields["client_completed_at"] = now

        supabase.table("jobs").update(update_fields).eq("uuid", internal_job_id).execute()

        tech_completed_now = update_fields.get("tech_completed", job.get("tech_completed") or False)
        client_completed_now = update_fields.get("client_completed", job.get("client_completed") or False)

        if tech_completed_now and client_completed_now:
            supabase.table("jobs").update({"status": "completed"}).eq("uuid", internal_job_id).execute()
            finalize_job_completion(job, internal_job_id)
            return {"success": True, "message": "Job fully completed", "status": "completed"}
        else:
            supabase.table("jobs").update({"status": "pending_completion"}).eq("uuid", internal_job_id).execute()

            if body.completed_by == "technician":
                verify_url = f"https://www.mayndstomir.com/status?id={job.get('tracking_token')}"
                verify_email_html = f"""
                <h2>Work Completed — Please Verify & Confirm</h2>
                <p>Hi {job.get('customer_name')},</p>
                <p>Your technician has marked the repair as complete. Please confirm to finalize the job.</p>
                <p><a href="{verify_url}">Confirm Completion</a></p>
                """
                send_email(
                    to_email=job.get("email"),
                    subject="Work Completed — Please Verify & Confirm",
                    html_content=verify_email_html
                )

            return {"success": True, "message": f"Completion recorded for {body.completed_by}; awaiting the other party", "status": "pending_completion"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/jobs/auto-close-check", dependencies=[Depends(verify_api_key)])
async def auto_close_stale_jobs():
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

        stale_jobs = supabase.table("jobs").select("*").eq("status", "pending_completion").eq("tech_completed", True).eq("client_completed", False).lte("tech_completed_at", cutoff).execute()

        closed_count = 0
        for job in stale_jobs.data:
            internal_job_id = job.get("uuid")
            now = datetime.now(timezone.utc).isoformat()

            supabase.table("jobs").update({
                "client_completed": True,
                "client_completed_at": now,
                "status": "completed"
            }).eq("uuid", internal_job_id).execute()

            finalize_job_completion(job, internal_job_id)
            closed_count += 1

        return {"success": True, "message": f"Auto-closed {closed_count} stale job(s)"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ReassignRequest(BaseModel):
    technician_id: int

class QuoteRequest(BaseModel):
    parts_cost: Optional[float] = 0
    sourcing_fee: Optional[float] = 0
    labor_cost: Optional[float] = 0
    notes: Optional[str] = None

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
        previous_technician_id = job.get("assigned_technician_id")

        supabase.table("jobs").update({
            "assigned_technician": assigned_name,
            "assigned_technician_id": body.technician_id,
            "status": "dispatched"
        }).eq("uuid", job_id).execute()

        supabase.table("technicians").update({
            "is_available": False
        }).eq("uuid", body.technician_id).execute()

        if previous_technician_id and previous_technician_id != body.technician_id:
            supabase.table("technicians").update({
                "is_available": True
            }).eq("uuid", previous_technician_id).execute()

            prev_assigned = supabase.table("technicians").select("assigned_jobs_count").eq("uuid", previous_technician_id).execute()
            if prev_assigned.data:
                current_prev = prev_assigned.data[0].get("assigned_jobs_count") or 0
                supabase.table("technicians").update({
                    "assigned_jobs_count": max(current_prev - 1, 0)
                }).eq("uuid", previous_technician_id).execute()

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
@app.patch("/jobs/{job_id}/accept", dependencies=[Depends(verify_api_key)])
async def accept_job(job_id: str):
    try:
        response = supabase.table("jobs").select("*").eq("tracking_token", job_id).execute()
        if not response.data:
            raise HTTPException(status_code=404, detail="Job not found")

        job = response.data[0]
        internal_job_id = job.get("uuid")

        if job.get("status") != "dispatched":
            raise HTTPException(status_code=400, detail=f"Job cannot be accepted from status '{job.get('status')}'")

        technician_id = job.get("assigned_technician_id")
        if not technician_id:
            raise HTTPException(status_code=400, detail="No technician assigned to this job")

        # Lock the technician NOW
        supabase.table("technicians").update({
            "is_available": False
        }).eq("uuid", technician_id).execute()

        # Increase assigned count
        tech_count = supabase.table("technicians").select("assigned_jobs_count").eq("uuid", technician_id).execute()
        if tech_count.data:
            current = tech_count.data[0].get("assigned_jobs_count") or 0
            supabase.table("technicians").update({
                "assigned_jobs_count": current + 1
            }).eq("uuid", technician_id).execute()

        supabase.table("jobs").update({
            "status": "in_diagnostics",
            "accepted_at": datetime.now(timezone.utc).isoformat()
        }).eq("uuid", internal_job_id).execute()

        tech_response = supabase.table("technicians").select("full_name, phone_number").eq("uuid", technician_id).execute()
        if tech_response.data:
            technician = tech_response.data[0]
            client_email_html = f"""
            <h2>Technician Assigned — En Route!</h2>
            <p>Hi {job.get('customer_name')},</p>
            <p><strong>{technician.get('full_name')}</strong> has accepted your request and will be en route shortly.</p>
            <p><strong>Technician Phone:</strong> {technician.get('phone_number')}</p>
            """
            send_email(
                to_email=job.get("email"),
                subject="Technician Assigned — En Route!",
                html_content=client_email_html
            )

        return {"success": True, "message": "Job accepted", "status": "in_diagnostics"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@app.patch("/jobs/{job_id}/reject", dependencies=[Depends(verify_api_key)])
async def decline_job(job_id: str):
    try:
        response = supabase.table("jobs").select("*").eq("tracking_token", job_id).execute()
        if not response.data:
            raise HTTPException(status_code=404, detail="Job not found")

        job = response.data[0]
        internal_job_id = job.get("uuid")
        declining_technician_id = job.get("assigned_technician_id")

        if job.get("status") != "dispatched":
            raise HTTPException(status_code=400, detail=f"Job cannot be declined from status '{job.get('status')}'")

        if declining_technician_id:
            supabase.table("technician_rejections").insert({
                "technician_id": declining_technician_id,
                "job_id": internal_job_id
            }).execute()

            supabase.table("technicians").update({
                "is_available": True
            }).eq("uuid", declining_technician_id).execute()

            job_tech_count = supabase.table("technicians").select("assigned_jobs_count").eq("uuid", declining_technician_id).execute()
            if job_tech_count.data:
                current_assigned = job_tech_count.data[0].get("assigned_jobs_count") or 0
                supabase.table("technicians").update({
                    "assigned_jobs_count": max(current_assigned - 1, 0)
                }).eq("uuid", declining_technician_id).execute()

        replacement = find_available_technician(
            job.get("category"),
            job.get("client_lat"),
            job.get("client_lng"),
            exclude_technician_id=declining_technician_id
        )

        if replacement:
            replacement_id = replacement.get("uuid")

            supabase.table("jobs").update({
                "assigned_technician": replacement.get("full_name"),
                "assigned_technician_id": replacement_id,
                "status": "dispatched"
            }).eq("uuid", internal_job_id).execute()

            current_replacement_assigned = replacement.get("assigned_jobs_count") or 0
            supabase.table("technicians").update({
                "assigned_jobs_count": current_replacement_assigned + 1
            }).eq("uuid", replacement_id).execute()

            maps_link = ""
            if job.get("client_lat") and job.get("client_lng"):
                maps_link = f"https://www.google.com/maps?q={job['client_lat']},{job['client_lng']}"

            email_html = f"""
            <h2>New {get_display_category(job.get('category')).upper()} Job Assigned</h2>
            <p><strong>Problem:</strong> {job.get('description')}</p>
            <p><strong>Client Phone:</strong> {job.get('phone_number')}</p>
            {'<p><strong>Live Location:</strong> <a href="' + maps_link + '">View on Map</a></p>' if maps_link else ''}
            """

            send_email(
                to_email=replacement.get("email_address"),
                subject=f"New {get_display_category(job.get('category')).upper()} Job - Action Needed",
                html_content=email_html,
                from_email="career@mayndstomir.com",
                from_name="MSA Careers"
            )

            return {"success": True, "message": "Job declined and re-dispatched", "status": "dispatched"}
        else:
            supabase.table("jobs").update({
                "assigned_technician": None,
                "assigned_technician_id": None,
                "status": "pending_dispatch"
            }).eq("uuid", internal_job_id).execute()

            return {"success": True, "message": "Job declined; no replacement available, queued", "status": "pending_dispatch"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

CALL_OUT_FEE = 50

@app.post("/jobs/{job_id}/quotes", dependencies=[Depends(verify_api_key)])
async def submit_quote(job_id: str, body: QuoteRequest):
    try:
        response = supabase.table("jobs").select("*").eq("tracking_token", job_id).execute()
        if not response.data:
            raise HTTPException(status_code=404, detail="Job not found")

        job = response.data[0]
        internal_job_id = job.get("uuid")

        if job.get("status") != "in_diagnostics":
            raise HTTPException(status_code=400, detail=f"Quote cannot be submitted from status '{job.get('status')}'")

        total_amount = CALL_OUT_FEE + (body.parts_cost or 0) + (body.sourcing_fee or 0) + (body.labor_cost or 0)
        payment_url = generate_payment_link(
            job_id=internal_job_id,
            amount=total_amount,
            tracking_token=job.get("tracking_token"),
            customer_name=job.get("customer_name"),
            phone_number=job.get("phone_number"),
            email=job.get("email")
        )
        

        supabase.table("jobs").update({
            "parts_cost": body.parts_cost,
            "sourcing_fee": body.sourcing_fee,
            "labor_cost": body.labor_cost,
            "quote_notes": body.notes,
            "total_amount": total_amount,
            "payment_url": payment_url,
            "status": "awaiting_payment"
        }).eq("uuid", internal_job_id).execute()

        invoice_url = f"https://www.mayndstomir.com/invoice?id={job.get('tracking_token')}"

        client_email_html = f"""
        <h2>Diagnostic Complete — Invoice Ready</h2>
        <p>Hi {job.get('customer_name')},</p>
        <p>Total amount due: QAR {total_amount:.2f}</p>
        <p><a href="{invoice_url}">View Invoice & Pay Now</a></p>
        """

        send_email(
            to_email=job.get("email"),
            subject="Diagnostic Complete — Invoice Ready",
            html_content=client_email_html
        )

        return {"success": True, "message": "Quote submitted", "total_amount": total_amount, "payment_url": payment_url}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@app.patch("/jobs/{job_id}/mark-paid", dependencies=[Depends(verify_api_key)])
async def mark_job_paid(job_id: str):
    try:
        response = supabase.table("jobs").select("*").eq("tracking_token", job_id).execute()
        if not response.data:
            raise HTTPException(status_code=404, detail="Job not found")

        job = response.data[0]
        internal_job_id = job.get("uuid")

        if job.get("status") != "awaiting_payment":
            raise HTTPException(status_code=400, detail=f"Job cannot be marked paid from status '{job.get('status')}'")

        supabase.table("jobs").update({
            "status": "paid",
            "paid_at": datetime.now(timezone.utc).isoformat()
        }).eq("uuid", internal_job_id).execute()

        technician_id = job.get("assigned_technician_id")
        if technician_id:
            tech_response = supabase.table("technicians").select("email_address, full_name").eq("uuid", technician_id).execute()
            if tech_response.data:
                technician = tech_response.data[0]
                proceed_email_html = f"""
                <h2>Payment Confirmed — Proceed with Repair</h2>
                <p>Hi {technician.get('full_name')},</p>
                <p>Payment has been confirmed for job at {job.get('customer_name')}. You may now proceed with the repair.</p>
                """
                send_email(
                    to_email=technician.get("email_address"),
                    subject="Payment Confirmed — Proceed with Repair",
                    html_content=proceed_email_html,
                    from_email="career@mayndstomir.com",
                    from_name="MSA Careers"
                )

        client_paid_email_html = f"""
        <h2>Payment Confirmed — Repair Authorized</h2>
        <p>Hi {job.get('customer_name')},</p>
        <p>Your payment has been confirmed. Your technician is now authorized to proceed with the repair.</p>
        """
        send_email(
            to_email=job.get("email"),
            subject="Payment Confirmed — Repair Authorized",
            html_content=client_paid_email_html
        )

        return {"success": True, "message": "Job marked as paid", "status": "paid"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@app.post("/payments/webhook")
async def skipcash_webhook(request: Request):
    try:
        body = await request.json()
        received_signature = request.headers.get("Authorization", "")

        payment_id = body.get("PaymentId")
        amount = body.get("Amount")
        status_id = body.get("StatusId")
        transaction_id = body.get("TransactionId")
        custom1 = body.get("Custom1")
        visa_id = body.get("VisaId")

        parts = [f"PaymentId={payment_id}", f"Amount={amount}", f"StatusId={status_id}"]
        if transaction_id:
            parts.append(f"TransactionId={transaction_id}")
        if custom1:
            parts.append(f"Custom1={custom1}")
        parts.append(f"VisaId={visa_id}")
        combined_data = ",".join(parts)

        expected_signature = compute_skipcash_signature(combined_data, SKIPCASH_WEBHOOK_KEY)

        if not hmac.compare_digest(expected_signature, received_signature):
            print("SkipCash webhook signature mismatch — rejecting.")
            raise HTTPException(status_code=401, detail="Invalid signature")

        if status_id != 2:
            return {"success": True, "message": "Webhook received, no action for this status"}

        if not transaction_id:
            return {"success": True, "message": "Webhook received, no transaction id to match"}

        job_response = supabase.table("jobs").select("*").eq("tracking_token", transaction_id).execute()
        if not job_response.data:
            return {"success": True, "message": "No matching job found"}

        job = job_response.data[0]
        if job.get("status") != "awaiting_payment":
            return {"success": True, "message": "Job already processed or not awaiting payment"}

        internal_job_id = job.get("uuid")
        supabase.table("jobs").update({
            "status": "paid",
            "paid_at": datetime.now(timezone.utc).isoformat()
        }).eq("uuid", internal_job_id).execute()

        technician_id = job.get("assigned_technician_id")
        if technician_id:
            tech_response = supabase.table("technicians").select("email_address, full_name").eq("uuid", technician_id).execute()
            if tech_response.data:
                technician = tech_response.data[0]
                proceed_email_html = f"""
                <h2>Payment Confirmed — Proceed with Repair</h2>
                <p>Hi {technician.get('full_name')},</p>
                <p>Payment has been confirmed for job at {job.get('customer_name')}. You may now proceed with the repair.</p>
                """
                send_email(
                    to_email=technician.get("email_address"),
                    subject="Payment Confirmed — Proceed with Repair",
                    html_content=proceed_email_html,
                    from_email="career@mayndstomir.com",
                    from_name="MSA Careers"
                )

        client_paid_email_html = f"""
        <h2>Payment Confirmed — Repair Authorized</h2>
        <p>Hi {job.get('customer_name')},</p>
        <p>Your payment has been confirmed. Your technician is now authorized to proceed with the repair.</p>
        """
        send_email(
            to_email=job.get("email"),
            subject="Payment Confirmed — Repair Authorized",
            html_content=client_paid_email_html
        )

        return {"success": True, "message": "Payment confirmed and job updated"}

    except HTTPException:
        raise
    except Exception as e:
        print(f"SkipCash webhook processing error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
@app.get("/email_failures", dependencies=[Depends(verify_api_key)])
async def get_email_failures():
    try:
        response = supabase.table("email_failures").select("*").order("created_at", desc=True).execute()
        return {"success": True, "data": response.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/jobs/{job_id}/cancel", dependencies=[Depends(verify_api_key)])
async def cancel_job(job_id: str):
    try:
        if job_id.isdigit():
            response = supabase.table("jobs").select("*").eq("uuid", int(job_id)).execute()
        else:
            response = supabase.table("jobs").select("*").eq("tracking_token", job_id).execute()

        if not response.data:
            raise HTTPException(status_code=404, detail="Job not found")

        job = response.data[0]
        internal_job_id = job.get("uuid")

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

        supabase.table("jobs").update({"status": "cancelled"}).eq("uuid", internal_job_id).execute()

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
            orphaned_jobs = supabase.table("jobs").select("*").eq("assigned_technician_id", worker_id).in_("status", ACTIVE_JOB_STATUSES).execute()

            still_unassigned = []
            if orphaned_jobs.data:
                for orphaned_job in orphaned_jobs.data:
                    replacement = find_available_technician(
                        orphaned_job.get("category"),
                        orphaned_job.get("client_lat"),
                        orphaned_job.get("client_lng"),
                        exclude_technician_id=worker_id
                    )

                    if replacement:
                        replacement_id = replacement.get("uuid")

                        supabase.table("jobs").update({
                            "assigned_technician": replacement.get("full_name"),
                            "assigned_technician_id": replacement_id,
                            "status": "dispatched"
                        }).eq("uuid", orphaned_job["uuid"]).execute()
                    

                        current_assigned = replacement.get("assigned_jobs_count") or 0
                        supabase.table("technicians").update({
                            "assigned_jobs_count": current_assigned + 1
                        }).eq("uuid", replacement_id).execute()

                        maps_link = ""
                        if orphaned_job.get("client_lat") and orphaned_job.get("client_lng"):
                            maps_link = f"https://www.google.com/maps?q={orphaned_job['client_lat']},{orphaned_job['client_lng']}"

                        reassign_email_html = f"""
                        <h2>New {get_display_category(orphaned_job.get('category')).upper()} Job Assigned</h2>
                        <p><strong>Problem:</strong> {orphaned_job.get('description')}</p>
                        <p><strong>Client Phone:</strong> {orphaned_job.get('phone_number')}</p>
                        {'<p><strong>Live Location:</strong> <a href="' + maps_link + '">View on Map</a></p>' if maps_link else ''}
                        """
                        send_email(
                            to_email=replacement.get("email_address"),
                            subject=f"New {get_display_category(orphaned_job.get('category')).upper()} Job - Action Needed",
                            html_content=reassign_email_html,
                            from_email="career@mayndstomir.com",
                            from_name="MSA Careers"
                        )
                    else:
                        supabase.table("jobs").update({
                            "assigned_technician": None,
                            "assigned_technician_id": None,
                            "status": "pending_dispatch"
                        }).eq("uuid", orphaned_job["uuid"]).execute()
                        still_unassigned.append(orphaned_job)

                supabase.table("technicians").update({
                    "assigned_jobs_count": 0
                }).eq("uuid", worker_id).execute()

                if still_unassigned:
                    orphaned_list_html = "".join(
                        f"<li>Job #MS-{str(j['uuid']).zfill(4)} — {get_display_category(j.get('category'))} — {j.get('customer_name')}</li>"
                        for j in still_unassigned
                    )
                    admin_alert_html = f"""
                    <h2>Technician Rejected — No Replacement Found</h2>
                    <p>{technician.get('full_name')} was rejected. {len(still_unassigned)} job(s) could not be auto-rematched to another technician and have been set back to pending:</p>
                    <ul>{orphaned_list_html}</ul>
                    <p>Please reassign manually.</p>
                    """
                    send_email(
                        to_email="customerservice@mayndstomir.com",
                        subject="Action Needed: Jobs Could Not Be Auto-Reassigned",
                        html_content=admin_alert_html
                    )

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