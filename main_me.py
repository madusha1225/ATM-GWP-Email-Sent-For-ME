import schedule
import time
import subprocess

def job():
    print("Running scripts...")
    subprocess.run(["python", "me_report_runner_only_one_me.py"])

# Run every day at 08:00 AM
schedule.every().day.at("08:30").do(job)

print("Scheduler started...")

while True:
    schedule.run_pending()
    time.sleep(60)