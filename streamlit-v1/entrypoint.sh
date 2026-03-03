#!/bin/bash
PORT=${PORT:-8080}
exec streamlit run app.py --server.port=$PORT --server.address=0.0.0.0 --logger.level=error