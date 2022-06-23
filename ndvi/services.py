import json
import os
import shutil
import urllib.parse as up
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import patoolib
import psycopg
import rasterio as rio
from dotenv import load_dotenv
from fastapi import HTTPException, status, Response
from fastapi.responses import FileResponse
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from rasterio.mask import mask
from sentinelsat import SentinelAPI, geojson_to_wkt

load_dotenv()
up.uses_netloc.append("postgres")
url = up.urlparse(os.getenv('DATABASE_URL'))


# Инициализация базы данных/таблицы
def db_init() -> "Create work table if not exists":
    table_script = """
                CREATE TABLE IF NOT EXISTS ndvi (
                    id serial PRIMARY KEY NOT NULL,
                    description text,
                    status boolean NOT NULL default false,
                    geojson json
                    )
                """
    with psycopg.connect(
            dbname=os.getenv('DB_NAME'),
            user=os.getenv('DB_USERNAME'),
            password=os.getenv('DB_PWD'),
            host=os.getenv('DB_URL'),
            row_factory=dict_row,
            options='-c statement_timeout=500') as connection:
        connection.execute(table_script)
        connection.commit()


# Генератор соединения с PostgreSQL
def db_connection() -> psycopg.Connection:
    session = psycopg.connect(
        dbname=os.getenv('DB_NAME'),
        user=os.getenv('DB_USERNAME'),
        password=os.getenv('DB_PWD'),
        host=os.getenv('DB_URL'),
        row_factory=dict_row,
        options='-c statement_timeout=500')
    try:
        yield session
    finally:
        session.close()


# Генератор соединения с SciHub
def api_connection() -> object:
    api = SentinelAPI(os.getenv('SAT_USER'),
                      os.getenv('SAT_PWD'),
                      "https://apihub.copernicus.eu/apihub")
    try:
        yield api
    finally:
        pass


# Загрузка информации о поле в базу
def add_field_to_db(connection: psycopg.Connection, name: str, file: dict) -> Response:
    add_script = "INSERT INTO ndvi (description, geojson) VALUES (%s, %s)"
    try:  # сохраняет название координаты поля в базе
        connection.execute(add_script, [name, Jsonb(file)])
        connection.commit()
        return Response(status_code=status.HTTP_201_CREATED)
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)


# Удаление информации о поле и его изображений
def delete_field_from_db(connection: psycopg.Connection, field_id: int) -> Response:
    path = f"./ndvi/map_data/{field_id}"
    if os.path.exists(path):
        shutil.rmtree(path)
    delete_script = f"DELETE FROM ndvi WHERE id = (%s)"
    db_response = connection.execute(delete_script, [field_id])
    connection.commit()
    if db_response.statusmessage.endswith('1'):
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


# Выгрузка NDVI изображения
def ndvi_download(field_id: int):
    image = f"./ndvi/map_data/{field_id}/NDVI_colored.png"
    if os.path.exists(image):
        return FileResponse(image, media_type="image/png")
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail={"message": "Файл не найден. Проверьте ID"})


# Полный список полей в базе
def get_fields(connection: psycopg.Connection,
               mode: 'representation mode(must be string "full" or not specified)' = None) -> list:
    list_script = """SELECT id, description, status FROM ndvi"""
    if mode == 'full':
        list_script = """SELECT * FROM ndvi WHERE status = false"""
    all_fields = connection.execute(list_script).fetchall()
    if len(all_fields) > 0:
        return all_fields
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


# Поиск наилучшего космического снимка по заданной области
def sat_dataset_search(api: SentinelAPI, geojson: dict) -> tuple or bool:
    # Преобразование словаря в съедобный формат для api scihub
    shaper = geojson_to_wkt(geojson)  # 4 знака после запятой по умолчанию
    # проверка допустимой длинны запроса
    if api.check_query_length(shaper) <= 1:
        products = api.query(shaper,
                             platformname='Sentinel-2',
                             date=("NOW-30DAYS", "NOW"),
                             cloudcoverpercentage=(0, 20),
                             order_by="+cloudcoverpercentage"
                             )
        geo_data = api.to_geodataframe(products)
        if len(products) > 0:
            product_id = geo_data.index[0]
            file_name = geo_data.filename[0]
            return product_id, file_name
        else:
            return False
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=".geojson содержит слишком длинный запрос. Уменьшите количество точек.")


# Утилита полного цилка обработки geojson с формированием TCI и NDVI снимков поля
class MainProcessor:
    def __init__(self, database: psycopg.Connection, scihub: SentinelAPI):

        self.db = database
        self.api = scihub
        np.seterr(divide='ignore', invalid='ignore')
        self._main()


    def _main(self):
        self.download_data = self._product_list_former()
        if not self.download_data:
            print("[INFO] Нет данных для скачивания")
            return
        self.work_dict, self.product_list = self.download_data
        self._sat_dataset_download()
        self._dataset_extractor()
        self._image_processor()

    # Поиск необработанных полей и формирование списка загрузки
    def _product_list_former(self) -> tuple or bool:
        print("[INFO] Поиск спутниковых данных")
        work_dict = {}
        product_id_list = []
        fields = get_fields(self.db, mode='full')
        for field in fields:
            map_data = sat_dataset_search(self.api, field["geojson"])
            if map_data:
                product_id, file_name = map_data
                work_dict[field["id"]] = {"file_name": file_name, "geojson": field["geojson"]}
                product_id_list.append(product_id)
        product_id_list = set(product_id_list)
        if len(product_id_list) > 0:
            return work_dict, product_id_list
        else:
            return False

    # Скачивание и распаковка пакета карт по индексу
    def _sat_dataset_download(self):
        print(f"[INFO] Начинаю скачивание")
        try:
            self.api.download_all(self.product_list, directory_path="./ndvi/temp")
            print("[INFO] Скачивание завершено")
        except Exception:
            print(f"Ошибка скачивания!")
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    # Извлечение спутниковых данных из архива
    @staticmethod
    def _dataset_extractor():
        print("[INFO] Извлечение данных")
        for element in os.scandir("./ndvi/temp"):
            if element.name.endswith(".zip"):
                patoolib.extract_archive(f"./ndvi/temp/{element.name}", outdir="./ndvi/temp")
                os.remove(f"./ndvi/temp/{element.name}")

    # Комлексный метод обработки изображений
    def _image_processor(self):
        print("[INFO] Обработка карт")
        for item in self.work_dict.items():
            file_id = item[0]
            b4_path, b8_path = self._pathfinder(item[1]["file_name"])
            self._map_composer(file_id, b4_path, b8_path)
            with open(f"./ndvi/map_data/{file_id}/{file_id}.geojson", "w") as file:
                file.write(json.dumps(item[1]["geojson"]))
                file.close()
            self._shaper(file_id)
            self._db_status_updater(file_id)
        print("[INFO] Обработка завершена")

    # Наложение диапазонов по заданной формуле
    @staticmethod
    def _map_composer(field_id, b4_path, b8_path):
        with rio.open(b4_path) as band_4:
            red = band_4.read(1).astype('float')
        with rio.open(b8_path) as band_8:
            nir = band_8.read(1).astype('float')
        ndvi = np.where((nir + red) == 0., 0, (nir - red) / (nir + red))
        del red, nir
        os.mkdir(f"./ndvi/map_data/{field_id}")
        with rio.open(
                f'./ndvi/map_data/{field_id}/NDVI.tiff',
                'w',
                driver='Gtiff',
                width=band_4.width,
                height=band_4.height,
                count=1,
                crs=band_8.crs,
                transform=band_8.transform,
                dtype='float32', ) as img:
            img.write(ndvi, 1)

    # Обрезка искомой области карты
    @staticmethod
    def _shaper(field_id):
        with rio.open(f"./ndvi/map_data/{field_id}/NDVI.tiff") as input_image:
            geojson_file = gpd.read_file(f"./ndvi/map_data/{field_id}/{field_id}.geojson")
            borders = geojson_file.to_crs(str(input_image.crs))
            output_image, output_transform = rio.mask.mask(input_image, borders.geometry, crop=True)
            output_meta = input_image.meta.copy()
            output_meta.update({"driver": "GTiff",
                                "height": output_image.shape[1],
                                "width": output_image.shape[2],
                                "transform": output_transform}, )
            with rio.open(f"./ndvi/map_data/{field_id}/NDVI_masked.tif", "w", **output_meta) as masked_map:
                masked_map.write(output_image)

        plt.imsave(f"./ndvi/map_data/{field_id}/NDVI_colored.png",
                   output_image[0],
                   cmap=plt.cm.viridis,
                   format="png")
        plt.close("all")

    # Поиск карт необходимых диапазонов в заданном каталоге
    @staticmethod
    def _pathfinder(catalog):
        with os.scandir(f"./ndvi/temp/{catalog}/GRANULE/") as entries:
            for entry in entries:
                path = f"./ndvi/temp/{catalog}/GRANULE/{entry.name}/IMG_DATA/"
                for file in os.scandir(path):
                    if file.name.endswith("B04.jp2"):
                        b4_path = path + file.name  # RED
                    elif file.name.endswith("B08.jp2"):
                        b8_path = path + file.name  # NIR
                return b4_path, b8_path

    # Обновление статуса обработки поля в базе
    def _db_status_updater(self, record_id, stat="true"):
        list_script = f"""UPDATE ndvi 
                        SET status = {stat}
                        WHERE id = (%s);"""
        try:
            self.db.execute(list_script, [record_id])
            self.db.commit()
        except Exception as error:
            raise error

    # Удаление спутниковых данных
    @staticmethod
    def _temp_flusher():
        if len(os.listdir("./ndvi/temp")) > 0:
            try:
                for map_dir in os.scandir("./ndvi/temp"):
                    if map_dir.is_dir():
                        shutil.rmtree(f"./ndvi/temp/{map_dir.name}")
                print("[INFO] Временные файлы удалены")
            except Exception as error:
                print(f"Не удалось очистить временные файлы: \n {error}")
                pass

    def __del__(self):
        self._temp_flusher()

