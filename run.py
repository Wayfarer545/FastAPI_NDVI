import os
import uvicorn
from dotenv import load_dotenv
from ndvi import app

load_dotenv()


if __name__ == '__main__':
    uvicorn.run(app,
                host=str(os.getenv('SERVER_HOST')),
                port=int(os.getenv('SERVER_PORT')),
                reload=False)
