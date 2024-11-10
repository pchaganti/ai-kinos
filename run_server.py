import os
import sys
import logging
from dotenv import load_dotenv

# Add the project root directory to Python path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

# Add the project root directory to Python path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from kinos_web import KinOSWeb

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_config():
    load_dotenv(override=True)
    
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    
    config = {
        "anthropic_api_key": anthropic_key,
        "openai_api_key": openai_key,
        "logger": logger.info
    }
    
    return config

# Create the application instance 
kinos = KinOSWeb(get_config())
app = kinos.get_app()  # This is the WSGI application

if __name__ == '__main__':
    if sys.platform == 'win32':
        # Windows - use waitress with error handling
        from waitress import serve
        try:
            print("Starting server on http://127.0.0.1:8000")
            serve(app, host='127.0.0.1', port=8000)
        except Exception as e:
            print(f"Error starting server: {e}")
    else:
        # Linux/Unix - use Flask's built-in server
        try:
            print("Starting server on http://0.0.0.0:8000")
            app.run(host='0.0.0.0', port=8000)
        except Exception as e:
            print(f"Error starting server: {e}")
