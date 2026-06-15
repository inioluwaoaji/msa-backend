import os
import httpx
from fastapi import FastAPI, APIRouter, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from supabase import create_client, Client

# Initialize FastAPI App
app = FastAPI(
    title="Maynd Stomir Backend API",
    description="Production backend pipeline handling jobs, tracking, and automated Twilio WhatsApp dispatch logic.",
    version="1.5.0"
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

# Kept for compatibility, though raw HTTP routing is used for database stability
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

    # 🛠️ FIXED: Automatically ignores unexpected or extra frontend fields 
    # (like 'photo_url') instead of throwing a validation crash or 500 database error.
    model_config = ConfigDict(extra="ignore")


# 4. Helper Function for Automated Outbound Twilio Notification
async def send_whatsapp_message(to_number: str, message: str):
    """
    Background worker that forwards the notification payload to the Twilio WhatsApp Sandbox.
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
                auth=(account_sid, auth_token)
            )
            response.raise_for_status()
            print(f"✅ WhatsApp alert successfully queued via Twilio to {formatted_to}")
        except httpx.HTTPError as e:
            print(f"❌ Twilio Communication Failure: {e}")


# 5. Core API Routes
@app.post("/jobs", status_code=201)
async def create_job(job: JobSubmission, background_tasks: BackgroundTasks):
    """
    Receives frontend maintenance requests and uses raw HTTP routing to force 
    data insertion directly into the target REST endpoint, bypassing PGRST125 path errors.
    """
    try:
        # Crucial: Using job.model_dump() here extracts ONLY the clean keys specified in our schema above.
        job_data = job.model_dump()
        
        raw_rest_url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/jobs"
        
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }
        
        async with httpx.AsyncClient() as client:
            db_response = await client.post(raw_rest_url, json=job_data, headers=headers)
            
            if db_response.status_code != 201 and db_response.status_code != 200:
                print(f"Direct REST failed ({db_response.status_code}), attempting explicit schema configuration...")
                headers["Accept-Profile"] = "public"
                headers["Content-Profile"] = "public"
                db_response = await client.post(raw_rest_url, json=job_data, headers=headers)
            
            db_response.raise_for_status()
            inserted_records = db_response.json()
        
        if not inserted_records:
            raise HTTPException(
                status_code=500, 
                detail="Database sync pending. Record failed to write cleanly inside the database map."
            )
        
        new_job = inserted_records[0]
        job_id = new_job.get("id")
        
        tracking_url = f"https://maynd-stomir.vercel.app/status.html?id={job_id}"
        
        notification_msg = (
            f"🛠️ *Maynd Stomir - Request Confirmed*\n\n"
            f"Hi {job.full_name},\n"
            f"Your maintenance request has been successfully processed.\n\n"
            f"📦 *Job ID:* {job_id}\n"
            f"📋 *Category:* {job.category}\n\n"
            f"🔗 *Track Your Job Progress Live:* {tracking_url}"
        )
        
        background_tasks.add_task(send_whatsapp_message, job.phone_number, notification_msg)
        
        return {
            "status": "success",
            "message": "Job logged successfully into Supabase!",
            "data": inserted_records
        }

    except Exception as error:
        print(f"Backend Direct REST Exception Logged: {str(error)}")
        error_detail = getattr(error, "response", None)
        detail_msg = error_detail.text if error_detail else str(error)
        raise HTTPException(
            status_code=500, 
            detail=f"Database Direct Route Failure. Context: {detail_msg}"
        )


@app.post("/webhook/whatsapp")
async def whatsapp_status_webhook(payload: dict, background_tasks: BackgroundTasks):
    """
    Dedicated operational webhook endpoint to handle status shifts.
    """
    record = payload.get("record", {})
    job_id = record.get("id")
    current_status = record.get("status", "PENDING")
    phone_number = record.get("phone_number")
    customer_name = record.get("full_name", "Customer")
    
    if not job_id or not phone_number:
        raise HTTPException(status_code=400, detail="Missing critical job tracking parameters.")
        
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