from app import app, db
from sqlalchemy import text

with app.app_context():
    with db.engine.connect() as connection:
        connection.execute(text('DELETE FROM alembic_version'))
