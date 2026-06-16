import os
import re
import httpx
from fastapi import FastAPI, APIRouter, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from supabase import create_client, Client

# Initialize FastAPI App
app = FastAPI(
    title="Maynd Stomir Backend API",
    description="Production backend pipeline handling jobs, tracking, freelance onboarding, and automated Twilio WhatsApp dispatch logic.",
    version="2.4.0"
)

# 1. CORS Configuration Security Layer
ORIGINS = [
    "https://maynd-stomir.vercel.app",
    "http://localhost:3000",
    "http://127.0.0.1:5500"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. Supabase Configuration Environment Variables
SUPABASE_URL: str = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY: str = os.environ.get("SUPABASE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️ WARNING: Missing Supabase Environment Variables!")

# Kept for architectural compatibility; raw HTTP endpoints are leveraged for connection pooling stability
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# 3. Pydantic Models for Validation
class JobSubmission(BaseModel):
    full_name: str = Field(..., description="Must match the names on uploaded QID.")
    phone_number: str = Field(..., min_length=8, max_length=8, description="Must be restricted to exactly 8 digits.")
    description: str
    category: str
    preferred_date: str
    preferred_time: str
    id_photo_url: Optional[str] = None
    job_photo_url: Optional[str] = None

    # Automatically ignores unexpected or extra fields instead of crashing
    model_config = ConfigDict(extra="ignore")


class AssignTechnicianPayload(BaseModel):
    technician_name: str = Field(..., alias="assigned_technician")


class FreelanceApplication(BaseModel):
    full_name: str = Field(..., description="Applicant's full name.")
    phone_number: str = Field(..., min_length=8, max_length=8, description="Exactly 8 digits.")
    email: str = Field(..., description="Contact email address.")
    category: str = Field(..., alias="trade", description="Maps frontend 'trade' selection to backend category field.")
    experience_years: int = Field(..., description="Years of field experience.")
    qid_number: str = Field(..., description="Qatar ID Number validation requirement.")
    description: Optional[str] = Field(None, description="Detailed text box of what they do.")
    id_photo_url: Optional[str] = None

    # Allows populating using either the python field name or frontend 'trade' alias
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


# 4. Data Extraction & Contract Transformation Helpers
def extract_location_field(description: str, field_name: str) -> Optional[str]:
    """
    Scans description text using regular expressions to extract location details
    e.g., matching 'Zone 45', 'Street 230', or 'Building 20'.
    """
    pattern = rf"{field_name}\s*(\d+)"
    match = re.search(pattern, description, re.IGNORECASE)
    return match.group(1) if match else None


def map_to_api_contract(db_record: dict) -> dict:
    """
    Translates raw database column schemas back into the exact names 
    agreed upon in the frontend API contract specification.
    """
    return {
        "id": db_record.get("uuid"),  # Map primary key database 'uuid' column directly to 'id'
        "full_name": db_record.get("customer_name"),
        "phone_number": db_record.get("phone_number"),
        "category": db_record.get("category") or db_record.get("problem_category"),
        "description": db_record.get("description"),
        "job_photo_url": db_record.get("photo_url"),
        "id_photo_url": db_record.get("photo_url"),
        "status": db_record.get("status"),
        "zone_number": db_record.get("zone_number"),
        "street_number": db_record.get("street_number"),
        "building_number": db_record.get("building_number"),
        "customer_availability": db_record.get("customer_availability"),
        "assigned_technician": db_record.get("assigned_technician"),
        "created_at": db_record.get("created_at")
    }


# 5. Helper Function for Automated Outbound Twilio Notification
async def send_whatsapp_message(to_number: str, message: str):
    """
    Background worker that forwards notifications to the Twilio WhatsApp interface.
    """
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    from_number = "whatsapp:+14155238886"
    
    if not account_sid or not auth_token:
        print("❌ Error: Twilio environment variables (SID/TOKEN) are not set.")
        return

    gateway_url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    
    clean_number = to_number.strip().replace(" ", "").replace("+", "")
    formatted_to = f"whatsapp:+{clean_number}"

    payload = {
        "From": from_number,
        "To": formatted_to,
        "Body": message
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                gateway_url, 
                data=payload, 
                auth=(account_sid, account_sid if not auth_token else auth_token)
            )
            response.raise_for_status()
            print(f"✅ WhatsApp alert successfully queued via Twilio to {formatted_to}")
        except httpx.HTTPError as e:
            print(f"❌ Twilio Communication Failure: {e}")


# 6. Core API Routes

# --- CUSTOMER JOB PIPELINE ---

@app.post("/jobs", status_code=201)
async def create_job(job: JobSubmission, background_tasks: BackgroundTasks):
    """
    Receives frontend maintenance submissions, normalizes values to raw database 
    columns, and outputs structural responses mapped exactly to the frontend contract.
    """
    try:
        job_data = job.model_dump()
        desc = job_data.get("description") or ""
        
        # Parse structural positioning indices directly from description string if present
        zone = extract_location_field(desc, "Zone")
        street = extract_location_field(desc, "Street")
        building = extract_location_field(desc, "Building")

        # Normalize dates and times into a unified availability property
        availability = None
        if job_data.get("preferred_date"):
            availability = f"{job_data['preferred_date']} {job_data.get('preferred_time', '')}".strip()

        # Sanitize undefined or broken text strings gracefully
        if "undefined" in desc.lower() or not desc.strip():
            desc = f"Maintenance requested for category: {job.category}."

        # Map frontend data payload fields to exact target database columns
        supabase_payload = {
            "customer_name": job_data.get("full_name"),
            "phone_number": job_data.get("phone_number"),
            "category": job_data.get("category"),
            "problem_category": job_data.get("category"),
            "description": desc,
            "photo_url": job_data.get("job_photo_url") or job_data.get("id_photo_url"),
            "zone_number": zone,
            "street_number": street,
            "building_number": building,
            "customer_availability": availability,
            "status": "PENDING"
        }

        base_url = SUPABASE_URL.strip().split("/rest/v1")[0]
        raw_rest_url = f"{base_url.rstrip('/')}/rest/v1/jobs"
        
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }
        
        async with httpx.AsyncClient() as client:
            db_response = await client.post(raw_rest_url, json=supabase_payload, headers=headers)
            db_response.raise_for_status()
            inserted_records = db_response.json()
        
        if not inserted_records:
            raise HTTPException(status_code=500, detail="Database save failed.")
        
        # Map back to API Contract layout format for Olamiposi's frontend response
        formatted_response = map_to_api_contract(inserted_records[0])
        job_id = formatted_response.get("id")
        
        tracking_url = f"https://maynd-stomir.vercel.app/status.html?id={job_id}"
        
        notification_msg = (
            f"🛠️ *Maynd Stomir - Request Confirmed*\n\n"
            f"Hi {formatted_response['full_name']},\n"
            f"Your maintenance request has been successfully processed.\n\n"
            f"📦 *Job ID:* {job_id}\n"
            f"📋 *Category:* {formatted_response['category']}\n\n"
            f"🔗 *Track Your Job Progress Live:* {tracking_url}"
        )
        
        background_tasks.add_task(send_whatsapp_message, job.phone_number, notification_msg)
        
        return {
            "status": "success",
            "message": "Job logged successfully into Supabase!",
            "data": [formatted_response]
        }

    except Exception as error:
        print(f"POST /jobs error exception: {str(error)}")
        raise HTTPException(status_code=500, detail=str(error))


@app.get("/jobs/{job_id}")
async def get_job_by_id(job_id: str):
    """
    Queries database logs dynamically utilizing 'uuid' filtering matching the schema.
    """
    try:
        base_url = SUPABASE_URL.strip().split("/rest/v1")[0]
        raw_rest_url = f"{base_url.rstrip('/')}/rest/v1/jobs?uuid=eq.{job_id}"
        
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Accept": "application/json"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(raw_rest_url, headers=headers)
            response.raise_for_status()
            records = response.json()
            
        if not records:
            raise HTTPException(status_code=404, detail="Job not found.")
            
        return map_to_api_contract(records[0])
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Job lookup execution tracing failure: {str(e)}")


@app.get("/jobs")
async def get_all_jobs():
    """
    Fetches comprehensive set of job objects back to the dashboard management panels.
    """
    try:
        base_url = SUPABASE_URL.strip().split("/rest/v1")[0]
        raw_rest_url = f"{base_url.rstrip('/')}/rest/v1/jobs?order=created_at.desc"
        
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Accept": "application/json"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(raw_rest_url, headers=headers)
            response.raise_for_status()
            records = response.json()
            
        return [map_to_api_contract(rec) for rec in records]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Global job stream extraction halted: {str(e)}")


@app.get("/jobs/lookup/{phone_number}")
async def lookup_jobs_by_phone(phone_number: str):
    """
    Queries the database log matching target historical phone records.
    """
    try:
        base_url = SUPABASE_URL.strip().split("/rest/v1")[0]
        raw_rest_url = f"{base_url.rstrip('/')}/rest/v1/jobs?phone_number=eq.{phone_number.strip()}"
        
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Accept": "application/json"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(raw_rest_url, headers=headers)
            response.raise_for_status()
            records = response.json()
            
        return [map_to_api_contract(rec) for rec in records]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Phone indexing stream execution failed: {str(e)}")


@app.patch("/jobs/{job_id}/assign")
async def assign_technician(job_id: str, payload: AssignTechnicianPayload):
    """
    Binds a technician to a specific task instance shifting state status to ASSIGNED.
    """
    try:
        base_url = SUPABASE_URL.strip().split("/rest/v1")[0]
        raw_rest_url = f"{base_url.rstrip('/')}/rest/v1/jobs?uuid=eq.{job_id}"
        
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }
        
        update_data = {
            "assigned_technician": payload.technician_name,
            "status": "ASSIGNED"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.patch(raw_rest_url, json=update_data, headers=headers)
            response.raise_for_status()
            records = response.json()
            
        if not records:
            raise HTTPException(status_code=404, detail="Target tracking reference non-existent.")
            
        return {"status": "success", "message": "Technician assignment mapped.", "data": map_to_api_contract(records[0])}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Technician process allocation breakdown: {str(e)}")


# --- FREELANCE ONBOARDING PIPELINE ---

@app.post("/freelance_applications", status_code=201)
async def create_freelance_application(application: FreelanceApplication, background_tasks: BackgroundTasks):
    """
    Receives incoming freelancer/technician applications and routes them straight to the database.
    (Updated payload structural mappings to match exact database screenshot design columns perfectly)
    """
    try:
        app_data = application.model_dump()
        
        # Append full name alongside years of experience directly inside description to preserve data structural continuity safely
        extended_description = (
            f"Applicant Name: {app_data.get('full_name')} | "
            f"Experience: {app_data.get('experience_years')} Years | "
            f"Details: {app_data.get('description') or 'None provided.'}"
        )
        
        # Build payload matching your exact database schema names
        supabase_payload = {
            "phone_number": app_data.get("phone_number"),
            "whatsapp_number": app_data.get("phone_number"),
            "email_address": app_data.get("email"),
            "trade_skill": app_data.get("category"),
            "qid_number": app_data.get("qid_number"),
            "description": extended_description,
            "id_photo_url": app_data.get("id_photo_url")
        }

        base_url = SUPABASE_URL.strip().split("/rest/v1")[0]
        raw_rest_url = f"{base_url.rstrip('/')}/rest/v1/freelance_applications"
        
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }
        
        async with httpx.AsyncClient() as client:
            db_response = await client.post(raw_rest_url, json=supabase_payload, headers=headers)
            db_response.raise_for_status()
            inserted_records = db_response.json()
            
        if not inserted_records:
            raise HTTPException(status_code=500, detail="Failed to log freelance application data.")

        # Automation drop: Send confirmation message to the applying technician via WhatsApp
        notification_msg = (
            f"🛠️ *Maynd Stomir - Application Received*\n\n"
            f"Hi {app_data['full_name']},\n"
            f"Thank you for applying to join our network as a freelance technician.\n\n"
            f"📋 *Category:* {app_data['category']}\n"
            f"Status: Our operations team is currently reviewing your credentials. We will be in touch shortly!"
        )
        background_tasks.add_task(send_whatsapp_message, application.phone_number, notification_msg)

        return {
            "status": "success",
            "message": "Freelance application submitted successfully!",
            "data": inserted_records[0]
        }

    except Exception as error:
        print(f"POST /freelance_applications error: {str(error)}")
        raise HTTPException(status_code=500, detail=f"Application intake pipeline failed: {str(error)}")


# --- GLOBAL SYSTEM ENDPOINTS ---

@app.post("/webhook/whatsapp")
async def whatsapp_status_webhook(payload: dict, background_tasks: BackgroundTasks):
    """
    Automated status shift webhook listener triggering WhatsApp tracking alerts.
    """
    record = payload.get("record", {})
    job_id = record.get("uuid") or record.get("id")
    current_status = record.get("status", "PENDING")
    phone_number = record.get("phone_number")
    customer_name = record.get("customer_name", "Customer")
    
    if not job_id or not phone_number:
        raise HTTPException(status_code=400, detail="Missing operational webhook parameters.")
        
    tracking_url = f"https://maynd-stomir.vercel.app/status.html?id={job_id}"
    
    update_msg = (
        f"🛠️ *Maynd Stomir Status Update*\n\n"
        f"Hello {customer_name},\n"
        f"The status of your maintenance request (Job ID: {job_id}) has changed to: *{current_status}*.\n\n"
        f"👉 *Monitor live technician updates here:* {tracking_url}"
    )
    
    background_tasks.add_task(send_whatsapp_message, phone_number, update_msg)
    return {"status": "success", "message": "WhatsApp tracking status dispatch processed."}


@app.get("/health")
async def health_check():
    return {"status": "healthy", "environment": "production"}