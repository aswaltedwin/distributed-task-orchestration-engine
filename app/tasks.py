import time

def send_email(payload: dict):
    print(f"Sending email to {payload.get('to')}...")
    time.sleep(2) # simulate delay
    print("Email sent successfully!")

def generate_report(payload: dict):
    print(f"Generating report with data {payload}...")
    time.sleep(5)
    print("Report generated!")

def chaos_sleep(payload: dict):
    duration = payload.get("duration", 10)
    print(f"Chaos task starting ({duration}s sleep)...")
    time.sleep(duration)
    print("Chaos task finished!")

def infinite_loop(payload: dict):
    while True:
        time.sleep(1)

def echo(payload: dict):
    print(f"Echo: {payload}")

# Task registry maps task names to handler functions
TASK_REGISTRY = {
    "send_email": send_email,
    "generate_report": generate_report,
    "infinite_loop": infinite_loop,
    "echo": echo,
    "chaos_sleep": chaos_sleep
}
