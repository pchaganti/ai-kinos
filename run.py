from flask import Flask
from parallagon_web import ParallagonWeb
import logging
import os
from dotenv import load_dotenv

def get_config():
    # Load environment variables from .env file
    load_dotenv()
    
    return {
        "anthropic_api_key": os.getenv("ANTHROPIC_API_KEY", "your-api-key-here"),
        "openai_api_key": os.getenv("OPENAI_API_KEY", "your-api-key-here")
    }

def signal_handler(signum, frame):
    logger.info("Received shutdown signal")
    app.shutdown()
    sys.exit(0)

def main():
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger(__name__)
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        config = get_config()
        
        # Check if API keys are properly loaded
        if config["anthropic_api_key"] == "your-api-key-here":
            logger.warning("ANTHROPIC_API_KEY not found in environment variables")
        if config["openai_api_key"] == "your-api-key-here":
            logger.warning("OPENAI_API_KEY not found in environment variables")
    
        # Initialize the ParallagonWeb application
        logger.info("Initializing ParallagonWeb application...")
        app = ParallagonWeb(config)
        
        # Get the Flask app instance
        flask_app = app.get_app()
        
        logger.info("Starting Parallagon Web with gevent-websocket...")
        logger.info("Server running at http://0.0.0.0:5000")
        
        # Run with Flask's development server
        flask_app.run(host='0.0.0.0', port=5000, debug=True)

    except Exception as e:
        logger.error(f"Failed to start server: {str(e)}")
        raise

if __name__ == "__main__":
    main()
