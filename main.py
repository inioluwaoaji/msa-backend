import os
import httpx
from fastapi import FastAPI, APIRouter, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List
from supabase import create_client, Client

# Initialize FastAPI App
app = FastAPI(
    title="Maynd Stomir Backend API",
    description="Production backend pipeline handling jobs, tracking, and automated Twilio WhatsApp dispatch logic.",
    version="1.3.0"
)

# 1. CORS Configuration Security Layer
# Resolves the origin blockages between Vercel and Render
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

# 2. Supabase Production Connection Client
# Initialized cleanly to resolve foreign table configuration issues
SUPABASE_URL: str = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY: str = os.environ.get("SUPABASE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️ WARNING: Missing Supabase Environment Variables!")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# 3. Pydantic Models for Validation
# Enforces backend validation constraints matching the marketplace operational rules
class JobSubmission(BaseModel):
    full_name: str = Field(..., description="Must match the names on uploaded QID.")
    phone_number: str = Field(..., min_length=8, max_length=8, description="Must be restricted to exactly 8 digits.")
    description: str
    category: str
    preferred_date: str
    preferred_time: str
    id_photo_url: Optional[str] = None
    job_photo_url: Optional[str] = None


# 4. Helper Function for Automated Outbound Twilio Notification
async def send_whatsapp_message(to_number: str, message: str):
    """
    Background worker that forwards the notification payload to the Twilio WhatsApp Sandbox.
    """
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    from_number = "whatsapp:+14155238886"  # Standard Twilio Sandbox Number
    
    if not account_sid or not auth_token:
        print("❌ Error: Twilio environment variables (SID/TOKEN) are not set.")
        return

    gateway_url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    
    # Clean up phone number format to ensure it works internationally (e.g., whatsapp:+974XXXXXXXX)
    clean_number = to_number.strip().replace(" ", "").replace("+", "")
    formatted_to = f"whatsapp:+{clean_number}"

    payload = {
        "From": from_number,
        "To": formatted_to,
        "Body": message
    }
    
    async with httpx.AsyncClient() as client:
        try:
            # Twilio utilizes HTTP Basic Auth (Account SID as username, Auth Token as password)
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
    Receives frontend maintenance request payloads, inserts them directly 
    via an explicit RPC procedure to bypass standard PostgREST foreign table path restrictions.
    """
    try:
        # Convert validation model to a clean dictionary
        job_data = job.model_dump()
        
        # 💡 FIX: Use RPC to invoke a direct database insert function 
        # This completely avoids the PGRST125 path routing issue with external/foreign tables
        db_query = supabase.rpc("insert_job_record", {"job_input": job_data}).execute()
        inserted_records = getattr(db_query, "data", [])
        
        # Fallback mechanism: If the RPC function isn't deployed on the database yet,
        # we fall back to a direct table insert but log issues cleanly.
        if not inserted_records:
            db_query = supabase.table("jobs").insert(job_data).execute()
            inserted_records = getattr(db_query, "data", [])

        if not inserted_records:
            raise HTTPException(
                status_code=500, 
                detail="Database sync pending. Record failed to write cleanly inside the foreign table map."
            )
        
        new_job = inserted_records[0]
        job_id = new_job.get("id")
        
        # Tracking link structure
        tracking_url = f"https://maynd-stomir.vercel.app/status.html?id={job_id}"
        
        # Construct the world-class notification layout string
        notification_msg = (
            f"🛠️ *Maynd Stomir - Request Confirmed*\n\n"
            f"Hi {job.full_name},\n"
            f"Your maintenance request has been successfully processed.\n\n"
            f"📦 *Job ID:* {job_id}\n"
            f"📋 *Category:* {job.category}\n\n"
            f"🔗 *Track Your Job Progress Live:* {tracking_url}"
        )
        
        # Dispatch the notification to run in the background so the user's form submission stays instant
        background_tasks.add_task(send_whatsapp_message, job.phone_number, notification_msg)
        
        # Return pristine JSON structure back to Olamiposi's frontend script to fetch the job ID
        return {
            "status": "success",
            "message": "Job logged successfully into Supabase!",
            "data": inserted_records
        }

    except Exception as error:
        print(f"Backend PostgREST/RPC Exception Logged: {str(error)}")
        raise HTTPException(
            status_code=500, 
            detail=f"Database Route Fault: PostgREST path failure or foreign table map mismatch. Context: {str(error)}"
        )


@app.post("/webhook/whatsapp")
async def whatsapp_status_webhook(payload: dict, background_tasks: BackgroundTasks):
    """
    Dedicated operational webhook endpoint to handle status shifts (e.g. real-time tracking updates from the dashboard).
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