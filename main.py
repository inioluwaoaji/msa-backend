import os
import re
import httpx
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, APIRouter, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
from typing import Optional, List
from supabase import create_client, Client

# Initialize FastAPI App
app = FastAPI(
    title="Maynd Stomir Backend API",
    description="Production backend pipeline handling jobs, tracking, freelance onboarding, and automated Twilio WhatsApp dispatch logic.",
    version="2.11.0"
)

# CORS Configuration Layer
ORIGINS = [
    "https://maynd-stomir.vercel.app",
    "https://mayndstomir.com",
    "https://www.mayndstomir.com",
    "http://localhost:5500",
    "http://127.0.0.1:5500"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Supabase Configuration Environment Variables
SUPABASE_URL: str = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY: str = os.environ.get("SUPABASE_KEY", "")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 🌐 ACTUAL WHATSAPP GROUP INVITE LINK FOR VERIFIED TECHNICIANS
ACTUAL_WHATSAPP_GROUP_URL = "https://chat.whatsapp.com/Dx3TDUz1WsMJc1qaUJ4RNo"


# --- 🗺️ REGIONAL GEOTARGETING MIDDLEWARE ENGINE ---
async def enforce_qatar_geographic_origin(request: Request):
    x_forwarded = request.headers.get("x-forwarded-for")
    client_ip = x_forwarded.split(",")[0].strip() if x_forwarded else request.client.host
    
    if client_ip in ["127.0.0.1", "localhost", "testclient"]:
        return {"country": "Qatar", "city": "Doha (Simulated)"}
        
    try:
        async with httpx.AsyncClient() as client:
            geo_lookup = await client.get(f"http://ip-api.com/json/{client_ip}", timeout=2.5)
            if geo_lookup.status_code == 200:
                geo_data = geo_lookup.json()
                if geo_data.get("status") == "success":
                    country = geo_data.get("country", "")
                    if country.lower() != "qatar":
                        raise HTTPException(
                            status_code=403, 
                            detail=f"Access Denied: Submission must originate inside Qatar. Detected: {country}"
                        )
                    return {"country": country, "city": geo_data.get("city", "Doha")}
    except HTTPException as http_err:
        raise http_err
    except Exception:
        pass
    return {"country": "Qatar", "city": "Doha (Default)"}


# --- 📋 VALIDATION SCHEMAS ---

class JobSubmission(BaseModel):
    full_name: str = Field(..., description="Must match the names on uploaded QID.")
    phone_number: str = Field(..., min_length=8, max_length=8, description="Must be restricted to exactly 8 digits.")
    email: Optional[str] = Field(None, description="Customer intake email field.")
    description: str
    category: str  
    preferred_date: str
    preferred_time: str
    id_photo_url: Optional[str] = None
    job_photo_url: Optional[str] = None

    model_config = ConfigDict(extra="ignore")

    @field_validator('full_name')
    @classmethod
    def validate_double_name(cls, value: str) -> str:
        clean_name = value.strip()
        if len(clean_name.split()) < 2:
            raise ValueError("Full name must include at least both a first and last name as shown on the QID.")
        return clean_name

    @field_validator('category')
    @classmethod
    def validate_customer_problem_category(cls, value: str) -> str:
        valid_options = {
            "hvac", "plumbing", "electrical", "painting", "carpentry", 
            "flooring", "appliance_repair", "pest_control", "cleaning", 
            "masonry", "glass_windows", "locks_security", "other"
        }
        clean_val = value.strip().lower()
        if clean_val not in valid_options:
            raise ValueError(f"Invalid problem category submission: {value}")
        return clean_val


class AssignTechnicianPayload(BaseModel):
    technician_name: str = Field(..., alias="assigned_technician")


class FreelanceApplication(BaseModel):
    full_name: str = Field(..., description="Applicant's full name.")
    phone_number: str = Field(..., min_length=8, max_length=8, description="Exactly 8 digits.")
    email: str = Field(..., description="Contact email address.")
    category: str = Field(..., alias="trade", description="Maps frontend choice to backend category.")
    experience_years: int = Field(..., description="Years of field experience.")
    qid_number: str = Field(..., description="Qatar ID Number validation requirement.")
    kahramaa_id: Optional[str] = Field(None, description="Mandatory ID certificate code for Electricians, Plumbers, and HVAC technicians.")
    description: Optional[str] = Field(None, description="Detailed text box of what they do.")
    id_photo_url: Optional[str] = None

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    @field_validator('full_name')
    @classmethod
    def validate_double_name(cls, value: str) -> str:
        clean_name = value.strip()
        if len(clean_name.split()) < 2:
            raise ValueError("Full name must include at least both a first and last name.")
        return clean_name

    @field_validator('qid_number')
    @classmethod
    def validate_strict_qatar_id(cls, value: str) -> str:
        clean_qid = value.strip()
        if not re.match(r"^[23]\d{10}$", clean_qid):
            raise ValueError("Security Rejection: Invalid QID structure. Field requires a valid 11-digit Qatar ID.")
        return clean_qid

    @field_validator('category')
    @classmethod
    def validate_technician_trade_category(cls, value: str) -> str:
        valid_options = {
            "hvac", "plumbing", "electrical", "carpentry", 
            "appliance_repair", "cleaning", "masonry", "other"
        }
        clean_val = value.strip().lower()
        if clean_val not in valid_options:
            raise ValueError(f"Invalid technician trade selection: {value}")
        return clean_val

    @model_validator(mode='after')
    def enforce_kahramaa_approval_gate(self) -> 'FreelanceApplication':
        trade_lower = (self.category or "").lower()
        if trade_lower in ["electrical", "plumbing", "hvac"]:
            if not self.kahramaa_id or not self.kahramaa_id.strip():
                raise ValueError(f"Regulatory Restriction: Valid Kahramaa Approval status is mandatory for all Qatari {trade_lower.upper()} profiles.")
        return self


def map_to_api_contract(db_record: dict) -> dict:
    zone = db_record.get("zone_number")
    street = db_record.get("street_number")
    building = db_record.get("building_number")
    
    if zone and street and building:
        navigation_map_url = f"https://www.google.com/maps/search/?api=1&query=Building+{building}+Street+{street}+Zone+{zone}+Doha+Qatar"
    else:
        navigation_map_url = "https://www.google.com/maps/search/?api=1&query=Doha+Qatar"

    return {
        "id": db_record.get("uuid"),
        "full_name": db_record.get("customer_name"),
        "phone_number": db_record.get("phone_number"),
        "email": db_record.get("email"),
        "category": db_record.get("category") or db_record.get("problem_category"),
        "description": db_record.get("description"),
        "job_photo_url": db_record.get("photo_url"),
        "id_photo_url": db_record.get("photo_url"),
        "status": db_record.get("status"),
        "zone_number": zone,
        "street_number": street,
        "building_number": building,
        "customer_availability": db_record.get("customer_availability"),
        "assigned_technician": db_record.get("assigned_technician"),
        "navigation_map_url": navigation_map_url,
        "created_at": db_record.get("created_at")
    }


def extract_location_field(description: str, field_name: str) -> Optional[str]:
    pattern = rf"{field_name}\s*(\d+)"
    match = re.search(pattern, description, re.IGNORECASE)
    return match.group(1) if match else None


async def send_whatsapp_message(to_number: str, message: str):
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    from_number = "whatsapp:+14155238886"
    
    if not account_sid or not auth_token:
        print("❌ Error: Twilio credentials absent.")
        return

    gateway_url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    clean_number = to_number.strip().replace(" ", "").replace("+", "")
    formatted_to = f"whatsapp:+{clean_number}"

    payload = {"From": from_number, "To": formatted_to, "Body": message}
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(gateway_url, data=payload, auth=(account_sid, auth_token))
            response.raise_for_status()
        except httpx.HTTPError as e:
            print(f"❌ Twilio routing block: {e}")


# --- 🚀 SECURED API ROUTE CONTROLLERS ---

@app.post("/jobs", status_code=201)
async def create_job(job: JobSubmission, request: Request, background_tasks: BackgroundTasks):
    await enforce_qatar_geographic_origin(request)
    try:
        job_data = job.model_dump()
        desc = job_data.get("description") or ""
        
        zone = extract_location_field(desc, "Zone")
        street = extract_location_field(desc, "Street")
        building = extract_location_field(desc, "Building")

        availability = None
        if job_data.get("preferred_date"):
            availability = f"{job_data['preferred_date']} {job_data.get('preferred_time', '')}".strip()

        # Build clean payload to eliminate potential multi-mapping schema mismatches
        supabase_payload = {
            "customer_name": job_data.get("full_name"),
            "phone_number": job_data.get("phone_number"),
            "email": job_data.get("email"),
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
        
        formatted_response = map_to_api_contract(inserted_records[0])
        job_id = formatted_response.get("id")
        tracking_url = f"https://maynd-stomir.vercel.app/status.html?id={job_id}"
        
        notification_msg = (
            f"🛠️ *Maynd Stomir - Request Confirmed*\n\n"
            f"Hi {formatted_response['full_name']},\n"
            f"Your order is verified. Tracking live here: {tracking_url}"
        )
        background_tasks.add_task(send_whatsapp_message, job.phone_number, notification_msg)
        return {"status": "success", "data": [formatted_response]}
    except Exception as error:
        # Pull detailed response text from internal HTTP client errors if available for faster diagnostic debugging
        error_detail = str(error)
        if hasattr(error, 'response') and error.response is not None:
            error_detail = f"{error.response.status_code}: {error.response.text}"
        raise HTTPException(status_code=500, detail=error_detail)


@app.get("/jobs/lookup/{phone_number}")
async def lookup_job_by_phone(phone_number: str):
    try:
        clean_phone = phone_number.strip().replace(" ", "").replace("+", "")
        if clean_phone.startswith("974") and len(clean_phone) > 8:
            clean_phone = clean_phone[3:]
            
        base_url = SUPABASE_URL.strip().split("/rest/v1")[0]
        raw_rest_url = f"{base_url.rstrip('/')}/rest/v1/jobs?phone_number=eq.{clean_phone}&order=created_at.desc"
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Accept": "application/json"}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(raw_rest_url, headers=headers)
            response.raise_for_status()
            records = response.json()
            
        if not records:
            raise HTTPException(status_code=404, detail="No active service tickets found under this phone number.")
            
        return [map_to_api_contract(rec) for rec in records]
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/freelance_applications", status_code=201)
async def create_freelance_application(application: FreelanceApplication, request: Request, background_tasks: BackgroundTasks):
    await enforce_qatar_geographic_origin(request)
    base_url = SUPABASE_URL.strip().split("/rest/v1")[0]
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    
    check_url = f"{base_url.rstrip('/')}/rest/v1/freelance_applications?qid_number=eq.{application.qid_number}&order=created_at.desc&limit=1"
    
    async with httpx.AsyncClient() as client:
        check_res = await client.get(check_url, headers=headers)
        if check_res.status_code == 200:
            past_submissions = check_res.json()
            if past_submissions:
                latest_record = past_submissions[0]
                if latest_record.get("status") == "REJECTED":
                    created_str = latest_record.get("created_at", "").replace("Z", "+00:00")
                    try:
                        rejection_time = datetime.fromisoformat(created_str)
                        if datetime.now(timezone.utc) - rejection_time < timedelta(days=30):
                            raise HTTPException(
                                status_code=400, 
                                detail="Policy Notice: Application blocked. Following a profile rejection, you must wait a minimum of 30 days before reapplying."
                            )
                    except HTTPException as http_err:
                        raise http_err
                    except Exception:
                        raise HTTPException(status_code=400, detail="Policy Notice: Profile cooling-off restriction active.")

    try:
        app_data = application.model_dump()
        extended_description = f"Applicant Name: {app_data.get('full_name')} | Experience: {app_data.get('experience_years')} Years"
        
        supabase_payload = {
            "phone_number": app_data.get("phone_number"),
            "whatsapp_number": app_data.get("phone_number"),
            "email_address": app_data.get("email"),
            "trade_skill": app_data.get("category"),
            "qid_number": app_data.get("qid_number"),
            "kahramaa_id": app_data.get("kahramaa_id"),
            "description": extended_description,
            "id_photo_url": app_data.get("id_photo_url"),
            "status": "PENDING",
            "link_used": False
        }

        raw_rest_url = f"{base_url.rstrip('/')}/rest/v1/freelance_applications"
        post_headers = {**headers, "Content-Type": "application/json", "Prefer": "return=representation"}
        
        async with httpx.AsyncClient() as client:
            db_response = await client.post(raw_rest_url, json=supabase_payload, headers=post_headers)
            db_response.raise_for_status()
            inserted_records = db_response.json()

        notification_msg = f"🛠️ *Maynd Stomir - Application Logged*\n\nThank you {app_data['full_name']}. Your application with trade category '{app_data['category']}' is currently under operational review."
        background_tasks.add_task(send_whatsapp_message, application.phone_number, notification_msg)
        return {"status": "success", "data": inserted_records[0]}
    except Exception as error:
        if isinstance(error, HTTPException):
            raise error
        raise HTTPException(status_code=500, detail=str(error))


@app.patch("/jobs/{job_id}/assign")
async def assign_technician(job_id: str, payload: AssignTechnicianPayload, background_tasks: BackgroundTasks):
    try:
        base_url = SUPABASE_URL.strip().split("/rest/v1")[0]
        raw_rest_url = f"{base_url.rstrip('/')}/rest/v1/jobs?uuid=eq.{job_id}"
        
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }
        update_data = {"assigned_technician": payload.technician_name, "status": "ASSIGNED"}
        
        async with httpx.AsyncClient() as client:
            response = await client.patch(raw_rest_url, json=update_data, headers=headers)
            response.raise_for_status()
            records = response.json()
            
        if not records:
            raise HTTPException(status_code=404, detail="Job entry not found.")
            
        formatted_data = map_to_api_contract(records[0])
        
        technician_alert = (
            f"🚀 *Maynd Stomir - New Route Assigned*\n\n"
            f"Hello {payload.technician_name},\n"
            f"You have been successfully assigned to Job #{job_id}.\n\n"
            f"🗺️ *Follow Live Navigation to Client:* \n"
            f"{formatted_data['navigation_map_url']}"
        )
        background_tasks.add_task(send_whatsapp_message, formatted_data['phone_number'], technician_alert)
        return {"status": "success", "data": formatted_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/webhook/freelancer_status")
async def update_freelancer_status_webhook(payload: dict, background_tasks: BackgroundTasks):
    record = payload.get("record", {})
    new_status = record.get("status", "PENDING")
    phone_number = record.get("phone_number")
    worker_name = record.get("full_name") or "Technician"
    freelancer_id = record.get("uuid") or record.get("id") or "token"
    
    if new_status == "APPROVED" and phone_number:
        secure_one_time_url = f"https://mayndstomir.com/verify-onboard.html?id={freelancer_id}"
        
        onboarding_msg = (
            f"🎉 *Welcome to Maynd Stomir, {worker_name}!*\n\n"
            f"Your profile has been officially verified and approved.\n\n"
            f"⚠️ *Secure One-Time Onboarding Invite Link:* \n"
            f"Click the link below to confirm your account and join your localized team cluster. "
            f"For security, this link is uniquely tied to your profile and will stop working once activated:\n"
            f"{secure_one_time_url}"
        )
        background_tasks.add_task(send_whatsapp_message, phone_number, onboarding_msg)
        
    return {"status": "processed"}


@app.post("/workers/{id}/verify")
async def verify_one_time_link(id: str):
    try:
        base_url = SUPABASE_URL.strip().split("/rest/v1")[0]
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Accept": "application/json"
        }
        
        lookup_url = f"{base_url.rstrip('/')}/rest/v1/freelance_applications?uuid=eq.{id}"
        async with httpx.AsyncClient() as client:
            res = await client.get(lookup_url, headers=headers)
            res.raise_for_status()
            records = res.json()
            
        if not records:
            raise HTTPException(status_code=404, detail="Invalid token session identifier.")
            
        record = records[0]
        
        if record.get("link_used") is True:
            raise HTTPException(status_code=410, detail="This security invite link has already been used and has expired.")
            
        if record.get("status") != "APPROVED":
            raise HTTPException(status_code=403, detail="Access Denied: Profile application state is unverified.")

        update_url = f"{base_url.rstrip('/')}/rest/v1/freelance_applications?uuid=eq.{id}"
        update_headers = {**headers, "Content-Type": "application/json", "Prefer": "return=representation"}
        async with httpx.AsyncClient() as client:
            patch_res = await client.patch(update_url, json={"link_used": True}, update_headers)
            patch_res.raise_for_status()

        return {
            "status": "verified",
            "message": "Authentication successful.",
            "whatsapp_group_url": ACTUAL_WHATSAPP_GROUP_URL
        }
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/jobs/{job_id}")
async def get_job_by_id(job_id: str):
    try:
        base_url = SUPABASE_URL.strip().split("/rest/v1")[0]
        raw_rest_url = f"{base_url.rstrip('/')}/rest/v1/jobs?uuid=eq.{job_id}"
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Accept": "application/json"}
        async with httpx.AsyncClient() as client:
            response = await client.get(raw_rest_url, headers=headers)
            response.raise_for_status()
            records = response.json()
        if not records:
            raise HTTPException(status_code=404, detail="Job not found.")
        return map_to_api_contract(records[0])
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.get("/jobs")
async def get_all_jobs():
    try:
        base_url = SUPABASE_URL.strip().split("/rest/v1")[0]
        raw_rest_url = f"{base_url.rstrip('/')}/rest/v1/jobs?order=created_at.desc"
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Accept": "application/json"}
        async with httpx.AsyncClient() as client:
            response = await client.get(raw_rest_url, headers=headers)
            response.raise_for_status()
            records = response.json()
        return [map_to_api_contract(rec) for rec in records]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
@app.head("/health")
async def health_check():
    return {"status": "healthy", "environment": "production"}