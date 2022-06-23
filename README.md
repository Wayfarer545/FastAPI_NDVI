### FastAPI web-service, providing satellite maps, processed accordingly NDVI algorythm.  
_______

Postman JSON collection link: https://www.getpostman.com/collections/51555ffee2be2f09b2cc  
DockerHub repository: https://hub.docker.com/repository/docker/wayfarer737/ndvi  
VDS: on request

### General information
REST API based on FastAPI and Uvicorn engine.  
You can load fields in .geojson format, delete and list it.  
When all the fields are uploaded to database - start processing and  
after some time you'll be able to download colored images, processed   
accordingly to NDVI algorithm.  
Service requires at least 12Gb RAM during processing of satellite map images.  
Sad but true and i'm going to optimize it later.

___
### Standalone deploy
requirements: python 3.8+, upgraded pip, PostgreSQL server
1. Clone repository
2. Go to project root catalog
3. Create new venv
4. Install requirements and export environment variables listed below:
```bash
$ git clone https://github.com/Wayfarer545/FastAPI_NDVI && cd FastAPI_NDVI
$ python3 -m venv some_env
$ source some_env/bin/activate
$ python3 -m pip install -r requirements.txt
$ export SERVER_HOST="0.0.0.0" ...
```
...or you can use .env file  
In this case the project root directory .env file should be specified as: 
```bash
SERVER_HOST="0.0.0.0"  
SERVER_PORT="8000"  
SAT_USER="SciHub user"  
SAT_PWD="SciHub password"  
DB_URL="PG URL"  
DB_USERNAME="PG username"  
DB_PWD="PG PWD"  
DB_NAME="PG db name"  
```
and finally run application:
```bash
& python3 run.py
```
___
### Docker deploy:  
Service can be used as a Docker container.  

 Docker-compose.yaml file example below. 
 Here you can see the working postgres parsable link. My own, of course. 

```yaml
version: '3.6'
services:
  FastAPI_NDVI:
    image: wayfarer737/ndvi:latest
    container_name: fastapi_ndvi
    restart: always
    ports:
      - "8000:8000"
    environment:
      ## Database connection
      DB_URL: ""
      DB_USERNAME: ""
      DB_PWD: ""
      DB_NAME: ""
      ## SciHub credentials
      SAT_USER: "user"
      SAT_PWD: "password"
      ## Uvicorn settings
      SERVER_HOST: "0.0.0.0"
      SERVER_PORT: 8000
    volumes:
      - /first/catalog:/app/temp ## massive temp files
      - /second/catalog:/app/map_data ## result of map images processing
networks:
  default:
    external:
      name: dark_net
```
