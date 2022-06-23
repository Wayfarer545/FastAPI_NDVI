from ast import literal_eval
from fastapi import (
    BackgroundTasks,
    UploadFile,
    APIRouter,
    Depends,
    File,
    Form
)
from fastapi.encoders import jsonable_encoder
from psycopg import Connection
from sentinelsat import SentinelAPI
from .services import *

# Инициализация роутера
router = APIRouter(prefix='/api')


# Создание таблицы ndvi в БД
@router.on_event("startup")
def on_startup():
    db_init()


# добавление geojson и имени поля в базу
@router.post("/upload_geo")
async def add_geojson(file: UploadFile = File(),
                      name: str = Form(),
                      database: Connection = Depends(db_connection)):
    geojson = literal_eval(jsonable_encoder(file.file.read()))
    return add_field_to_db(database, name, geojson)


# вывод списка всех полей из базы
@router.get("/show_fields")
async def get_fields_list(database: Connection = Depends(db_connection)):
    return get_fields(database, mode='full')


# удаление информации о поле из базы и каталога по id
@router.delete("/delete_field/{field_id}")
async def delete_data(field_id: int,
                      database: Connection = Depends(db_connection)):
    return delete_field_from_db(database, field_id)


# запрос результата обратоки по id поля
@router.get("/download/{field_id}")
async def get_ndvi_image(field_id: int):
    return ndvi_download(field_id)


# запуск обработки новых полей
@router.post("/start_processing/")
async def start_processing_datasets(background: BackgroundTasks,
                                    db: Connection = Depends(db_connection),
                                    api: SentinelAPI = Depends(api_connection)):
    background.add_task(MainProcessor, db, api)
    return Response(status_code=status.HTTP_202_ACCEPTED)
