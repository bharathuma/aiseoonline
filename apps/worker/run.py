"""Worker entrypoint, used by celery -A run:celery_app worker."""

from aiseoonline_api.config import get_settings
from aiseoonline_api.jobs import create_celery_app

celery_app = create_celery_app(get_settings())
