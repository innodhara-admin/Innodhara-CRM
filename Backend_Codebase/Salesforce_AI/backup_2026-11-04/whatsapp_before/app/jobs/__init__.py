"""Background job registration."""
from app.jobs.docx_ocr import run_docx_ocr
from app.jobs.pipelines import plan_meeting_safe, process_meeting_safe
from app.jobs.queue import job_queue
from app.jobs.sender import send_message


def register_handlers() -> None:
    job_queue.register("process_meeting", process_meeting_safe)
    job_queue.register("plan_meeting", plan_meeting_safe)
    job_queue.register("send_message", send_message)
    job_queue.register("docx_ocr", run_docx_ocr)
