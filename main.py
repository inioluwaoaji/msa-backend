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

# 4. Root Health Check Route
@app.get("/")
async def root():
    return {"status": "healthy", "service": "MindStormerX Backend"}

# 5. Production Job Creation and Notification Route
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
        # Dispatch Alert Email to Technical Lead & Staff
        resend.Emails.send({
            "from": "Maynd Stomir Alerts <onboarding@resend.dev>",
            "to": ["olamiposi@yourdomain.com"],  # Swap with Olamiposi's real email
            "subject": f"🚨 New Job Assigned: {job.category.upper()}",
            "html": email_html_content
        })
        
        # Dispatch Confirmation Receipt to the Client
        resend.Emails.send({
            "from": "Maynd Stomir <onboarding@resend.dev>",
            "to": [job.email],
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