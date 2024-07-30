import os
import zipfile
import json
from flask import Flask, request, render_template, redirect, url_for
from pykml import parser
import folium
import tempfile
import geopandas as gpd
from pyproj import CRS

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['STATIC_FOLDER'] = 'static'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['STATIC_FOLDER'], exist_ok=True)

def extract_kml_from_kmz(kmz_path, output_path):
    with zipfile.ZipFile(kmz_path, 'r') as kmz:
        kmz.extractall(output_path)
    kml_files = [f for f in os.listdir(output_path) if f.endswith('.kml')]
    if not kml_files:
        raise ValueError("No se encontró ningún archivo KML en el KMZ.")
    return os.path.join(output_path, kml_files[0])

def convert_kml_to_geojson(kml_path, output_path):
    with open(kml_path, 'r', encoding='utf-8') as f:
        kml_data = f.read()
    root = parser.fromstring(kml_data.encode('utf-8'))
    geojson_features = []
    for placemark in root.Document.findall('.//{http://www.opengis.net/kml/2.2}Placemark'):
        geom = placemark.find('.//{http://www.opengis.net/kml/2.2}Polygon')
        if geom is not None:
            coordinates = geom.find('.//{http://www.opengis.net/kml/2.2}coordinates').text.strip()
            points = [list(map(float, coord.split(','))) for coord in coordinates.split()]
            polygon = {
                'type': 'Polygon',
                'coordinates': [[(point[0], point[1]) for point in points]]
            }
            properties = {elem.tag.split('}')[-1]: elem.text for elem in placemark.iterchildren() if elem.tag != '{http://www.opengis.net/kml/2.2}Polygon'}
            geojson_features.append({
                'type': 'Feature',
                'geometry': polygon,
                'properties': properties
            })
    geojson_data = {
        'type': 'FeatureCollection',
        'features': geojson_features
    }
    geojson_path = os.path.join(output_path, 'output.geojson')
    with open(geojson_path, 'w', encoding='utf-8') as geojson_file:
        json.dump(geojson_data, geojson_file)
    return geojson_path

def save_uploaded_files(files, upload_folder):
    saved_paths = []
    for file in files:
        file_path = os.path.join(upload_folder, file.filename)
        file.save(file_path)
        saved_paths.append(file_path)
    return saved_paths

def get_crs_from_prj(prj_path):
    with open(prj_path, 'r') as prj_file:
        prj_txt = prj_file.read()
    return CRS.from_wkt(prj_txt)

def convert_shapefile_to_geojson(uploaded_files, output_path):
    # Verificar que todos los archivos necesarios del shapefile estén presentes
    shapefile_path = None
    prj_path = None
    required_extensions = ['.shp', '.shx', '.dbf']
    for ext in required_extensions:
        for file_path in uploaded_files:
            if file_path.endswith(ext):
                if ext == '.shp':
                    shapefile_path = file_path
                break
        else:
            raise ValueError(f"Falta el archivo {ext}")

    for file_path in uploaded_files:
        if file_path.endswith('.prj'):
            prj_path = file_path
            break

    gdf = gpd.read_file(shapefile_path)
    if gdf.crs is None and prj_path:
        gdf.set_crs(get_crs_from_prj(prj_path), inplace=True)
    if gdf.crs is None:
        raise ValueError("No se encontró sistema de coordenadas en el Shapefile y no se proporcionó un CRS.")
    elif gdf.crs != 'EPSG:4326':
        gdf = gdf.to_crs(epsg=4326)
    geojson_path = os.path.join(output_path, 'output.geojson')
    gdf.to_file(geojson_path, driver='GeoJSON')
    return geojson_path

def create_html_map(geojson_path, map_path):
    with open(geojson_path, 'r', encoding='utf-8') as f:
        geojson_data = json.load(f)
    m = folium.Map(location=[-38.4161, -63.6167], zoom_start=5)
    folium.GeoJson(geojson_data).add_to(m)
    m.save(map_path)
    print(f"Mapa HTML guardado en: {map_path}")

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        if 'file' not in request.files:
            return redirect(request.url)
        files = request.files.getlist('file')
        if not files or files[0].filename == '':
            return redirect(request.url)
        if files:
            saved_paths = save_uploaded_files(files, app.config['UPLOAD_FOLDER'])
            output_path = tempfile.mkdtemp()
            try:
                if any(file.lower().endswith('.kmz') for file in saved_paths):
                    kmz_path = next(file for file in saved_paths if file.lower().endswith('.kmz'))
                    kml_path = extract_kml_from_kmz(kmz_path, output_path)
                    geojson_path = convert_kml_to_geojson(kml_path, output_path)
                elif any(file.lower().endswith('.shp') for file in saved_paths):
                    geojson_path = convert_shapefile_to_geojson(saved_paths, output_path)
                else:
                    return 'Formato de archivo no soportado', 400
                map_file_name = 'map.html'
                map_path = os.path.join(app.config['STATIC_FOLDER'], map_file_name)
                create_html_map(geojson_path, map_path)
                return redirect(url_for('map_view', map_file=map_file_name))
            except Exception as e:
                return str(e), 400
    return render_template('index_gis.html')

@app.route('/map')
def map_view():
    map_file = request.args.get('map_file')
    return render_template('map_gis.html', map_file=map_file)

if __name__ == '__main__':
    app.run(debug=True)
