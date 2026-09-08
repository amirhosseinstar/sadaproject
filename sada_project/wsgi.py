"""
WSGI config for sada_project.
این فایل برای اجرای پروژه روی سرورهای واقعی (مثل gunicorn) استفاده می‌شود.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sada_project.settings')

application = get_wsgi_application()
