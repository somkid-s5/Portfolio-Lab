"""Bounded connection pool; cloud mode always uses Cloud SQL private IP connector."""
import atexit
import json
import os
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL

def create_pool():
    config=json.loads(Path(os.environ['DB_CONFIG_FILE']).read_text())
    common={'pool_size':4,'max_overflow':0,'pool_timeout':3,'pool_pre_ping':True,
            'pool_recycle':300,'hide_parameters':True}
    if os.environ.get('DB_MODE','cloud')=='local':
        if os.environ.get('DEPLOYMENT_TARGET')=='gce':
            raise ValueError('Local DB mode is not allowed on deployed GCE workloads')
        engine=create_engine(URL.create('postgresql+pg8000',username=config['user'],
            password=config['password'],host=config.get('host','127.0.0.1'),
            port=int(config.get('port',5432)),database=config['database']),
            connect_args={'timeout':5},**common)
    else:
        from google.cloud.sql.connector import Connector, IPTypes
        connector=Connector(refresh_strategy='LAZY',timeout=5)
        atexit.register(connector.close)
        def connection():
            from pg8000 import OperationalError
            try:
                return connector.connect(os.environ['INSTANCE_CONNECTION_NAME'],'pg8000',
                  user=config['user'],password=config['password'],db=config['database'],
                  ip_type=IPTypes.PRIVATE,timeout=5)
            except Exception as exc:
                # IAM/API/network failures can precede the DB driver. Normalize them
                # without leaking connector URLs, tokens or secret-bearing messages.
                raise OperationalError('Cloud SQL connector unavailable: '+type(exc).__name__) from None
        engine=create_engine('postgresql+pg8000://',creator=connection,**common)
    @event.listens_for(engine,'connect')
    def limits(connection,record):
        cursor=connection.cursor()
        try:
            cursor.execute("SET statement_timeout = '5s'")
            cursor.execute("SET lock_timeout = '3s'")
            cursor.execute("SET TIME ZONE 'UTC'")
            connection.commit()
        finally:
            cursor.close()
    atexit.register(engine.dispose)
    return engine
