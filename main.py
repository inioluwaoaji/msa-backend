import os
import requests
from datetime import datetime
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, field_validator
from typing import Optional

# 1. Turn on the FastAPI engine
app = FastAPI(title="Maynd Stomir MVP API")

# 2. Your direct Supabase Project Credentials
SUPABASE_URL = "https://sukssqwzatvmnwdxthoa.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InN1a3NzcXd6YXR2bW53ZHh0aG9hIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODA4MjE0NjgsImV4cCI6MjA5NjM5NzQ2OH0.sT0wK2IAksWIycIwNvVqKJdQvXax4w4rPE5Mw8eppNo"  # <-- Remember to paste your real secret anon key string back here!

# 3. Security Rulebook for Customer Repair Jobs
class JobCreate(BaseModel):
    customer_name: str
    phone_number: str
    problem_category: str
    description: str
    photo_url: Optional[str] = ""
    zone_number: str
    street_number: str
    building_number: str
    customer_availability: str

# 4. Security Rulebook for Freelance Applications
class FreelanceApplicationCreate(BaseModel):
    email_address: str       
    whatsapp_number: str     
    trade_skill: str
    id_photo_url: str
    id_expiry_date: str      

    # --- ID EXPIRY RECOGNITION VALIDATOR ---
    @field_validator('id_expiry_date')
    @classmethod
    def check_id_not_expired(cls, value):
        try:
            expiry = datetime.strptime(value, "%Y-%m-%d")
            if expiry < datetime.now():
                raise ValueError("This identification card has expired. Please upload a valid ID.")
            return value
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail=str(error) if "expired" in str(error) else "Invalid date format. Use YYYY-MM-DD."
            )

# --- CORE INTEGRATION API ROUTES ---

@app.get("/")
def home():
    return {"message": "Maynd Stomir Backend Engine is Online!"}

@app.post("/jobs")
def create_customer_job(job: JobCreate):
    target_url = f"{SUPABASE_URL}/rest/v1/jobs"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    try:
        response = requests.post(target_url, json=job.dict(), headers=headers)
        return {"message": "Job submitted successfully!", "data": response.json()}
    except Exception as e:
        return {"error_details": str(e)}

@app.post("/freelance_applications")
def register_freelancer(application: FreelanceApplicationCreate):
    target_url = f"{SUPABASE_URL}/rest/v1/freelance_applications"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    try:
        response = requests.post(target_url, json=application.dict(), headers=headers)
        return {"message": "Application submitted successfully!", "data": response.json()}
    except Exception as e:
        return {"error_details": str(e)}

# --- LIVE MANAGEMENT DASHBOARD CONTROL ROUTES ---

@app.get("/dashboard", response_class=HTMLResponse)
def view_dashboard():
    try:
        with open("dashboard.html", "r", encoding="utf-8") as file:
            return HTMLResponse(content=file.read(), status_code=200)
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>dashboard.html file not found! Please place it in the same folder directory level as main.py</h1>", 
            status_code=404
        )

@app.get("/api/get_jobs")
def get_all_jobs_from_supabase():
    target_url = f"{SUPABASE_URL}/rest/v1/jobs?select=*"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }
    response = requests.get(target_url, headers=headers)
    return response.json()

@app.patch("/api/update_job_status")
def update_job_status_in_supabase(uuid: int, status: str):
    target_url = f"{SUPABASE_URL}/rest/v1/jobs?uuid=eq.{uuid}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    payload = {"status": status}
    response = requests.patch(target_url, json=payload, headers=headers)
    return response.json()

# --- DAY 4 FREELANCER ROUTING API ENDPOINTS ---

@app.get("/api/get_freelancers")
def get_all_freelancers_from_supabase():
    target_url = f"{SUPABASE_URL}/rest/v1/freelance_applications?select=*"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }
    try:
        response = requests.get(target_url, headers=headers)
        data = response.json()
        
        # 🔥 ASAP FALLBACK: If Supabase returns nothing, inject test data automatically!
        if not data or data == [] or (isinstance(data, dict) and "error" in data):
            print("⚠️ Supabase returned empty or errored. Applying Day 4 local mock freelancers!")
            return [
                {"email_address": "samuel.tech@example.com", "trade_skill": "AC Technician"},
                {"email_address": "blessing.elect@example.com", "trade_skill": "Electrical Specialist"},
                {"email_address": "olamiposi.fix@example.com", "trade_skill": "Plumber"}
            ]
        return data
    except Exception:
        # Fallback security if network fails completely
        return [
            {"email_address": "samuel.tech@example.com", "trade_skill": "AC Technician"},
            {"email_address": "blessing.elect@example.com", "trade_skill": "Electrical Specialist"}
        ]
@app.patch("/api/assign_technician")
def assign_technician_to_job(uuid: int, freelancer_email: str):
    target_url = f"{SUPABASE_URL}/rest/v1/jobs?uuid=eq.{uuid}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    payload = {"assigned_technician": freelancer_email}
    response = requests.patch(target_url, json=payload, headers=headers)
    return response.json()