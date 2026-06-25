import os
import resend
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# 1. Initialize FastAPI Application
app = FastAPI(title="MindStormerX API")

# 2. Initialize Resend Email Engine
resend.api_key = os.environ.get("RESEND_API_KEY")

# 3. Data Schema for Job Submissions
class JobSubmission(BaseModel):
    full_name: str
    email: str
    phone_number: str
    category: str
    description: str
    preferred_date: str
    preferred_time: str

# 4. Bulletproof Multi-Path & Multi-Method Health Check Routes (Uptime Monitor)
@app.api_route("", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/health", methods=["GET", "HEAD"], include_in_schema=False)
async def root_health_check():
    return {"status": "healthy", "service": "MindStormerX Backend"}

# 5. Production Job Creation and Notification Route (Live Custom Domain)
@app.post("/jobs", status_code=201)
async def create_job(job: JobSubmission):
    # TODO: Put your existing Supabase database insertion logic here
    # (e.g., supabase.table("jobs").insert(...))
    
    # Construct the internal operational notification email body
    email_html_content = f"""
    <h3>🛠️ New Job Request Submitted</h3>
    <hr/>
    <p><strong>Client Name:</strong> {job.full_name}</p>
    <p><strong>Email:</strong> {job.email}</p>
    <p><strong>Phone:</strong> {job.phone_number}</p>
    <p><strong>Category:</strong> {job.category}</p>
    <p><strong>Description:</strong> {job.description}</p>
    <p><strong>Preferred Slot:</strong> {job.preferred_date} at {job.preferred_time}</p>
    """
    
    try:
        # Dispatch Alert Email to Technical Lead & Staff (Olamiposi)
        resend.Emails.send({
            "from": "MindStormerX Alerts <alerts@mayndstomir.com>",
            "to": ["viewwhatsappstatus@gmail.com"],  # Your internal monitoring inbox
            "subject": f"🚨 New Job Assigned: {job.category.upper()}",
            "html": email_html_content
        })
        
        # Dispatch Confirmation Receipt to the Live Client
        resend.Emails.send({
            "from": "MindStormerX <support@mayndstomir.com>",
            "to": [job.email], # Sends globally to whichever email address is sent via Postman
            "subject": "🛠️ Your Service Request is Confirmed!",
            "html": f"""
            <h3>Hi {job.full_name},</h3>
            <p>We have successfully received your service request for <strong>{job.category}</strong>.</p>
            <p>Our localized technical cluster team is reviewing your description. A representative will contact you shortly.</p>
            <br/>
            <p>Best regards,<br/>The MindStormerX Team</p>
            """
        })
        
    except Exception as e:
        # Prevent email gateway delivery drops from failing database tracking operations
        print(f"Notification routing exception caught: {str(e)}")
        
    return {
        "status": "success", 
        "message": "Job record created successfully and communication dispatches triggered."
    }