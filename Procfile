web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
worker: celery -A app.workers.celery_app worker -Q pipeline_normal,pipeline_heavy --concurrency=4 --loglevel=info
beat: celery -A app.workers.celery_app beat --loglevel=info
