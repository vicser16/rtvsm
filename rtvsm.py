"""
TMDB File Renamer
----------------
Aplicación para renombrar archivos de series y películas usando la información de TMDB.

Características:
- Búsqueda y selección de series y películas en TMDB
- Vista previa del póster al seleccionar un título
- Detección automática de temporadas y episodios
- Organización en estructura de carpetas (Serie/Temporada/Episodios)
- Directorio base personalizable
- Gestión segura de hilos de trabajo

Correcciones de errores:
- Solucionado el error "QThread: Destroyed while thread is still running" implementando:
  1. Control adecuado del ciclo de vida de los hilos
  2. Método stop() en cada clase de hilo
  3. Limpieza de hilos al cerrar la aplicación
  4. Manejo correcto de QNetworkAccessManager

Autor: [Tu nombre]
Fecha: [Fecha]
"""

import sys
import os
import re
import json
import requests
import shutil
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                            QHBoxLayout, QPushButton, QFileDialog, QListWidget,
                            QListWidgetItem, QLabel, QComboBox, QLineEdit, QMessageBox, QProgressBar, QCheckBox,
                            QDialog, QScrollArea, QSizePolicy, QFrame, QGroupBox, QTabWidget)
from PyQt5.QtGui import QIcon, QFont, QPixmap, QColor
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize, QUrl
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

# Configuración de la API de TMDB
TMDB_API_KEY = "#"  # Necesitarás obtener una clave API de TMDB
TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"  # Base URL para imágenes

class TMDBSearchWorker(QThread):
    """Hilo para buscar en TMDB sin bloquear la interfaz"""
    finished = pyqtSignal(list)

    def __init__(self, search_term, search_type):
        super().__init__()
        self.search_term = search_term
        self.search_type = search_type
        self.is_running = True

    def run(self):
        if self.is_running:
            results = self.search_tmdb()
            self.finished.emit(results)

    def stop(self):
        self.is_running = False
        self.wait()  # Esperar a que termine

    def search_tmdb(self):
        try:
            url = f"{TMDB_BASE_URL}/search/{self.search_type}"
            params = {
                "api_key": TMDB_API_KEY,
                "query": self.search_term,
                "language": "es-ES"  # Búsqueda en español
            }
            response = requests.get(url, params=params)
            data = response.json()
            return data.get("results", [])
        except Exception as e:
            print(f"Error en la búsqueda TMDB: {e}")
            return []

class SeasonEpisodesFetcher(QThread):
    """Hilo para obtener episodios de una temporada"""
    finished = pyqtSignal(dict)

    def __init__(self, series_id, season_number):
        super().__init__()
        self.series_id = series_id
        self.season_number = season_number
        self.is_running = True

    def run(self):
        if self.is_running:
            episodes = self.fetch_season_episodes()
            self.finished.emit(episodes)

    def stop(self):
        self.is_running = False
        self.wait()  # Esperar a que termine

    def fetch_season_episodes(self):
        try:
            url = f"{TMDB_BASE_URL}/tv/{self.series_id}/season/{self.season_number}"
            params = {
                "api_key": TMDB_API_KEY,
                "language": "es-ES"
            }
            response = requests.get(url, params=params)
            data = response.json()

            episodes_dict = {}
            for episode in data.get("episodes", []):
                episode_number = episode.get("episode_number")
                episode_name = episode.get("name", "")
                episodes_dict[episode_number] = episode_name

            return episodes_dict
        except Exception as e:
            print(f"Error al obtener episodios: {e}")
            return {}

class AllSeasonsFetcher(QThread):
    """Hilo para obtener episodios de todas las temporadas de una serie"""
    finished = pyqtSignal(dict)

    def __init__(self, series_id, num_seasons):
        super().__init__()
        self.series_id = series_id
        self.num_seasons = num_seasons
        self.is_running = True

    def run(self):
        if self.is_running:
            all_episodes = self.fetch_all_seasons()
            self.finished.emit(all_episodes)

    def stop(self):
        self.is_running = False
        self.wait()  # Esperar a que termine

    def fetch_all_seasons(self):
        try:
            all_episodes = {}

            for season in range(1, self.num_seasons + 1):
                if not self.is_running:
                    break  # Salir si se detiene el hilo

                url = f"{TMDB_BASE_URL}/tv/{self.series_id}/season/{season}"
                params = {
                    "api_key": TMDB_API_KEY,
                    "language": "es-ES"
                }
                response = requests.get(url, params=params)
                data = response.json()

                season_episodes = {}
                for episode in data.get("episodes", []):
                    episode_number = episode.get("episode_number")
                    episode_name = episode.get("name", "")
                    season_episodes[episode_number] = episode_name

                all_episodes[season] = season_episodes

            return all_episodes
        except Exception as e:
            print(f"Error al obtener todas las temporadas: {e}")
            return {}

class PosterPreviewDialog(QDialog):
    """Diálogo para mostrar el póster original"""

    def __init__(self, parent=None, poster_path=None, title=""):
        super().__init__(parent)
        self.setWindowTitle(f"Póster de {title}")
        self.setMinimumSize(550, 600)
        self.layout = QVBoxLayout()

        # Etiqueta para mostrar el póster
        self.poster_label = QLabel()
        self.poster_label.setAlignment(Qt.AlignCenter)
        self.poster_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Área de desplazamiento para imágenes grandes
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(self.poster_label)

        self.layout.addWidget(scroll_area)

        # Botón para cerrar
        self.close_button = QPushButton("Cerrar")
        self.close_button.clicked.connect(self.accept)
        self.layout.addWidget(self.close_button)

        self.setLayout(self.layout)

        # Referencia al gestor de red
        self.network_manager = None

        # Cargar póster si se proporciona la ruta
        if poster_path:
            self.load_poster(poster_path)

    def load_poster(self, poster_path):
        """Cargar póster desde TMDB"""
        if not poster_path:
            self.poster_label.setText("No hay póster disponible")
            return

        poster_url = f"{TMDB_IMAGE_BASE_URL}{poster_path}"

        # Crear un gestor de red para descargar la imagen
        self.network_manager = QNetworkAccessManager()
        self.network_manager.finished.connect(self.handle_network_response)

        # Iniciar la descarga
        request = QNetworkRequest(QUrl(poster_url))
        self.network_manager.get(request)

    def handle_network_response(self, reply):
        """Manejar la respuesta de red para la descarga del póster"""
        if reply.error() == QNetworkReply.NoError:
            data = reply.readAll()
            pixmap = QPixmap()
            pixmap.loadFromData(data)

            # Escalar manteniendo la proporción si es demasiado grande
            if pixmap.height() > 800:
                pixmap = pixmap.scaledToHeight(800, Qt.SmoothTransformation)

            self.poster_label.setPixmap(pixmap)
        else:
            self.poster_label.setText("Error al cargar el póster")

        reply.deleteLater()

    def closeEvent(self, event):
        """Manejar el cierre del diálogo"""
        # Limpiar el gestor de red
        if self.network_manager:
            try:
                # Desconectar solo si hay conexiones
                if self.network_manager.receivers(self.network_manager.finished) > 0:
                    self.network_manager.finished.disconnect()
            except Exception as e:
                print(f"Error al desconectar señal en diálogo: {e}")
            self.network_manager = None
        event.accept()

class ConfigDialog(QDialog):
    """Diálogo para configuración de renombrado y opciones"""

    def __init__(self, parent=None, config=None):
        super().__init__(parent)
        self.setWindowTitle("Configuración de TMDB Renamer")
        self.setMinimumSize(600, 500)

        # Configuración actual o valores por defecto
        self.config = config or {
            "tv_format": 0,  # Formato de renombrado para series (índice)
            "movie_format": 0,  # Formato de renombrado para películas (índice)
            "download_posters": False,  # Descargar pósters
            "organize_movies": True,  # Organizar películas en carpetas
            "tv_formats": [
                "{title} S{season:02d}E{episode:02d}",  # Formato básico
                "{title} S{season:02d}E{episode:02d} {episode_title}",  # Con título de episodio
                "{title} - {season}x{episode:02d}",  # Formato alternativo
                "{title} - Temporada {season} Episodio {episode:02d}"  # En español
            ],
            "movie_formats": [
                "{title} ({year})",  # Formato básico
                "{title} [{year}]",  # Con corchetes
                "{title} {year}",  # Sin paréntesis
                "{title} - {year}"  # Con guión
            ]
        }

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # Pestañas para organizar la configuración
        tabs = QTabWidget()

        # Pestaña de formatos
        formats_tab = QWidget()
        formats_layout = QVBoxLayout()

        # Formatos para series
        tv_group = QGroupBox("Formato de renombrado para series")
        tv_layout = QVBoxLayout()

        self.tv_format_combo = QComboBox()
        for fmt in self.config["tv_formats"]:
            self.tv_format_combo.addItem(fmt)
        self.tv_format_combo.setCurrentIndex(self.config["tv_format"])
        self.tv_format_combo.currentIndexChanged.connect(self.update_tv_preview)

        tv_layout.addWidget(QLabel("Selecciona el formato de renombrado:"))
        tv_layout.addWidget(self.tv_format_combo)

        # Vista previa de formato para series
        tv_preview_label = QLabel("Vista previa:")
        self.tv_preview = QLabel()
        self.tv_preview.setStyleSheet("background-color: #f0f0f0; padding: 8px; border-radius: 4px;")
        tv_layout.addWidget(tv_preview_label)
        tv_layout.addWidget(self.tv_preview)

        tv_group.setLayout(tv_layout)
        formats_layout.addWidget(tv_group)

        # Separador
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        formats_layout.addWidget(line)

        # Formatos para películas
        movie_group = QGroupBox("Formato de renombrado para películas")
        movie_layout = QVBoxLayout()

        self.movie_format_combo = QComboBox()
        for fmt in self.config["movie_formats"]:
            self.movie_format_combo.addItem(fmt)
        self.movie_format_combo.setCurrentIndex(self.config["movie_format"])
        self.movie_format_combo.currentIndexChanged.connect(self.update_movie_preview)

        movie_layout.addWidget(QLabel("Selecciona el formato de renombrado:"))
        movie_layout.addWidget(self.movie_format_combo)

        # Vista previa de formato para películas
        movie_preview_label = QLabel("Vista previa:")
        self.movie_preview = QLabel()
        self.movie_preview.setStyleSheet("background-color: #f0f0f0; padding: 8px; border-radius: 4px;")
        movie_layout.addWidget(movie_preview_label)
        movie_layout.addWidget(self.movie_preview)

        movie_group.setLayout(movie_layout)
        formats_layout.addWidget(movie_group)

        formats_tab.setLayout(formats_layout)

        # Pestaña de organización
        organization_tab = QWidget()
        organization_layout = QVBoxLayout()

        # Opciones de organización
        self.organize_movies_checkbox = QCheckBox("Organizar películas en carpetas (Título (Año))")
        self.organize_movies_checkbox.setChecked(self.config["organize_movies"])

        self.download_posters_checkbox = QCheckBox("Descargar póster principal al crear directorios")
        self.download_posters_checkbox.setChecked(self.config["download_posters"])

        organization_layout.addWidget(self.organize_movies_checkbox)
        organization_layout.addWidget(self.download_posters_checkbox)
        organization_layout.addStretch()

        organization_tab.setLayout(organization_layout)

        # Añadir pestañas
        tabs.addTab(formats_tab, "Formatos de renombrado")
        tabs.addTab(organization_tab, "Organización")

        layout.addWidget(tabs)

        # Botones
        button_layout = QHBoxLayout()
        self.ok_button = QPushButton("Aceptar")
        self.cancel_button = QPushButton("Cancelar")

        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

        button_layout.addStretch()
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)

        layout.addLayout(button_layout)

        self.setLayout(layout)

        # Inicializar vistas previas
        self.update_tv_preview()
        self.update_movie_preview()

    def update_tv_preview(self):
        """Actualizar vista previa del formato de serie"""
        index = self.tv_format_combo.currentIndex()
        format_str = self.tv_format_combo.currentText()

        # Datos de ejemplo
        example = format_str.format(
            title="Breaking Bad",
            season=1,
            episode=5,
            episode_title="Gray Matter"
        )

        self.tv_preview.setText(f"{example}.mp4")
        self.config["tv_format"] = index

    def update_movie_preview(self):
        """Actualizar vista previa del formato de película"""
        index = self.movie_format_combo.currentIndex()
        format_str = self.movie_format_combo.currentText()

        # Datos de ejemplo
        example = format_str.format(
            title="The Shawshank Redemption",
            year="1994"
        )

        self.movie_preview.setText(f"{example}.mp4")
        self.config["movie_format"] = index

    def get_config(self):
        """Obtener la configuración actual"""
        self.config["organize_movies"] = self.organize_movies_checkbox.isChecked()
        self.config["download_posters"] = self.download_posters_checkbox.isChecked()
        return self.config

class EpisodesBySeasonView(QWidget):
    """Widget para mostrar episodios agrupados por temporadas"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.episodes_by_season = {}  # Diccionario {temporada: [episodios]}
        self.selected_season = None
        self.current_view = None  # 'list' o 'season'

        self.init_ui()

    def init_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setSpacing(10)  # Aumentar espacio entre elementos

        # Header con título e información
        self.header_layout = QHBoxLayout()
        self.title_label = QLabel("Episodios por temporada")
        self.title_label.setFont(QFont("Arial", 11, QFont.Bold))

        self.view_combo = QComboBox()
        self.view_combo.addItem("Vista de lista", "list")
        self.view_combo.addItem("Vista por temporadas", "season")
        self.view_combo.currentIndexChanged.connect(self.change_view)

        self.header_layout.addWidget(self.title_label)
        self.header_layout.addStretch()
        self.header_layout.addWidget(QLabel("Modo de vista:"))
        self.header_layout.addWidget(self.view_combo)

        self.layout.addLayout(self.header_layout)

        # Panel de temporadas (izquierda)
        self.seasons_panel = QWidget()
        self.seasons_layout = QVBoxLayout(self.seasons_panel)
        self.seasons_label = QLabel("Temporadas")
        self.seasons_label.setFont(QFont("Arial", 10, QFont.Bold))
        self.seasons_list = QListWidget()
        self.seasons_list.setMinimumWidth(250)  # Ancho mínimo para las temporadas
        self.seasons_list.itemClicked.connect(self.on_season_selected)

        self.seasons_layout.addWidget(self.seasons_label)
        self.seasons_layout.addWidget(self.seasons_list)

        # Panel de contenido principal (temporadas + episodios)
        self.content_panel = QWidget()
        self.content_layout = QHBoxLayout(self.content_panel)

        # Panel de episodios con dos columnas: original y nuevo nombre
        self.episodes_panel = QWidget()
        self.episodes_layout = QVBoxLayout(self.episodes_panel)

        # Título para el panel de episodios
        self.episodes_title = QLabel("Episodios")
        self.episodes_title.setFont(QFont("Arial", 10, QFont.Bold))
        self.episodes_layout.addWidget(self.episodes_title)

        # Layout horizontal para las dos columnas
        self.episodes_columns_layout = QHBoxLayout()

        # Panel de nombres originales (izquierda)
        self.original_panel = QWidget()
        self.original_layout = QVBoxLayout(self.original_panel)
        self.original_label = QLabel("Nombre original")
        self.original_label.setFont(QFont("Arial", 9, QFont.Bold))
        self.original_list = QListWidget()
        self.original_list.setMinimumHeight(450)  # Altura mínima aumentada

        self.original_layout.addWidget(self.original_label)
        self.original_layout.addWidget(self.original_list)

        # Panel de nombres nuevos (derecha)
        self.renamed_panel = QWidget()
        self.renamed_layout = QVBoxLayout(self.renamed_panel)
        self.renamed_label = QLabel("Nombre final")
        self.renamed_label.setFont(QFont("Arial", 9, QFont.Bold))
        self.renamed_list = QListWidget()
        self.renamed_list.setMinimumHeight(450)  # Altura mínima aumentada

        self.renamed_layout.addWidget(self.renamed_label)
        self.renamed_layout.addWidget(self.renamed_list)

        # Agregar los paneles de nombres al layout de columnas
        self.episodes_columns_layout.addWidget(self.original_panel)
        self.episodes_columns_layout.addWidget(self.renamed_panel)

        # Agregar el layout de columnas al panel de episodios
        self.episodes_layout.addLayout(self.episodes_columns_layout)

        # Agregar los paneles principales al layout de contenido
        self.content_layout.addWidget(self.seasons_panel, 1)
        self.content_layout.addWidget(self.episodes_panel, 3)  # Mayor proporción para los episodios

        # Panel alternativo para vista de lista
        self.list_panel = QWidget()
        self.list_layout = QVBoxLayout(self.list_panel)
        self.full_list = QListWidget()
        self.full_list.setMinimumHeight(500)  # Altura mínima aumentada
        self.list_layout.addWidget(self.full_list)

        # Stacked Widget para cambiar entre vistas
        self.stacked_widget = QTabWidget()
        self.stacked_widget.setTabPosition(QTabWidget.South)

        # Añadir los paneles al stacked widget
        self.stacked_widget.addTab(self.content_panel, "Por temporadas")
        self.stacked_widget.addTab(self.list_panel, "Lista completa")

        self.layout.addWidget(self.stacked_widget)

        # Ocultar inicialmente
        self.set_view("list")

    def set_episodes(self, episodes_by_season, original_names=None, new_names=None):
        """Establecer episodios organizados por temporada
        episodes_by_season: {temporada: {episodio_num: [(nombre_original, nuevo_nombre)]}}
        """
        self.episodes_by_season = episodes_by_season
        self.update_seasons_list()
        self.update_full_list()

        # Seleccionar la primera temporada si hay alguna
        if self.seasons_list.count() > 0:
            self.seasons_list.setCurrentRow(0)
            self.on_season_selected(self.seasons_list.item(0))

    def update_seasons_list(self):
        """Actualizar la lista de temporadas"""
        self.seasons_list.clear()

        for season in sorted(self.episodes_by_season.keys()):
            count = sum(len(episodes) for episodes in self.episodes_by_season[season].values())
            item = QListWidgetItem(f"Temporada {season} ({count} episodios)")
            item.setData(Qt.UserRole, season)
            # Aplicar estilo a todas las temporadas en la lista
            item.setBackground(QColor(200, 230, 255))
            item.setForeground(QColor(0, 0, 150))
            font = item.font()
            font.setBold(True)
            item.setFont(font)
            self.seasons_list.addItem(item)

    def update_full_list(self):
        """Actualizar la lista completa de episodios"""
        self.full_list.clear()

        for season in sorted(self.episodes_by_season.keys()):
            # Añadir cabecera de temporada
            season_header = QListWidgetItem(f"Temporada {season}")
            season_header.setBackground(QColor(200, 230, 255))
            season_header.setForeground(QColor(0, 0, 150))
            font = season_header.font()
            font.setBold(True)
            season_header.setFont(font)
            self.full_list.addItem(season_header)

            # Añadir episodios de esta temporada
            for episode_num in sorted(self.episodes_by_season[season].keys()):
                for original_name, new_name in self.episodes_by_season[season][episode_num]:
                    item = QListWidgetItem(f"  E{episode_num:02d}: {os.path.basename(original_name)} → {os.path.basename(new_name)}")
                    self.full_list.addItem(item)

            # Añadir separador
            if season != sorted(self.episodes_by_season.keys())[-1]:
                self.full_list.addItem("")

    def on_season_selected(self, item):
        """Manejar selección de temporada"""
        if not item:
            return

        season = item.data(Qt.UserRole)
        self.selected_season = season
        self.update_episodes_list()

    def update_episodes_list(self):
        """Actualizar la lista de episodios para la temporada seleccionada"""
        self.original_list.clear()
        self.renamed_list.clear()

        if self.selected_season is None or self.selected_season not in self.episodes_by_season:
            return

        for episode_num in sorted(self.episodes_by_season[self.selected_season].keys()):
            for original_name, new_name in self.episodes_by_season[self.selected_season][episode_num]:
                # Crear elementos para ambas listas
                original_item = QListWidgetItem(f"E{episode_num:02d}: {os.path.basename(original_name)}")
                renamed_item = QListWidgetItem(f"E{episode_num:02d}: {os.path.basename(new_name)}")

                # Almacenar los datos completos
                original_item.setData(Qt.UserRole, (original_name, new_name))
                renamed_item.setData(Qt.UserRole, (original_name, new_name))

                # Si es el primer episodio de la temporada, añadir encabezado
                if episode_num == sorted(self.episodes_by_season[self.selected_season].keys())[0]:
                    header_item_original = QListWidgetItem(f"Temporada {self.selected_season}")
                    header_item_renamed = QListWidgetItem(f"Temporada {self.selected_season}")

                    # Aplicar estilo a los encabezados
                    for header in [header_item_original, header_item_renamed]:
                        header.setBackground(QColor(200, 230, 255))
                        header.setForeground(QColor(0, 0, 150))
                        font = header.font()
                        font.setBold(True)
                        header.setFont(font)

                    self.original_list.addItem(header_item_original)
                    self.renamed_list.addItem(header_item_renamed)

                # Añadir los elementos a las listas
                self.original_list.addItem(original_item)
                self.renamed_list.addItem(renamed_item)

    def set_view(self, view_type):
        """Cambiar el tipo de vista ('list' o 'season')"""
        self.current_view = view_type

        if view_type == "list":
            self.stacked_widget.setCurrentIndex(1)
        else:
            self.stacked_widget.setCurrentIndex(0)

    def change_view(self, index):
        """Manejar cambio de vista desde el combo"""
        view_type = self.view_combo.currentData()
        self.set_view(view_type)

    def clear(self):
        """Limpiar todas las listas"""
        self.episodes_by_season = {}
        self.selected_season = None
        self.seasons_list.clear()
        self.original_list.clear()
        self.renamed_list.clear()
        self.full_list.clear()

class TMDBRenamer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TMDB File Renamer")
        self.setGeometry(100, 100, 1200, 800)  # Aumentar tamaño de la ventana

        # Almacena información de la serie o película seleccionada
        self.current_media_info = None
        self.episodes_info = {}  # Para una temporada específica
        self.all_seasons_info = {}  # Para todas las temporadas
        self.files_to_rename = []
        self.new_filenames = []
        self.selected_media_type = "tv"  # Por defecto, series
        self.detect_all_seasons = False  # Opción para detectar todas las temporadas
        self.base_directory = ""  # Directorio base personalizable

        # Configuración de la aplicación
        self.config = {
            "tv_format": 0,  # Formato de renombrado para series (índice)
            "movie_format": 0,  # Formato de renombrado para películas (índice)
            "download_posters": False,  # Descargar pósters
            "organize_movies": True,  # Organizar películas en carpetas
            "tv_formats": [
                "{title} S{season:02d}E{episode:02d}",  # Formato básico
                "{title} S{season:02d}E{episode:02d} {episode_title}",  # Con título de episodio
                "{title} - {season}x{episode:02d}",  # Formato alternativo
                "{title} - Temporada {season} Episodio {episode:02d}"  # En español
            ],
            "movie_formats": [
                "{title} ({year})",  # Formato básico
                "{title} [{year}]",  # Con corchetes
                "{title} {year}",  # Sin paréntesis
                "{title} - {year}"  # Con guión
            ]
        }

        # Referencias a los hilos activos
        self.search_worker = None
        self.episodes_fetcher = None
        self.all_seasons_fetcher = None
        self.network_manager = None

        self.init_ui()

    def init_ui(self):
        main_widget = QWidget()
        main_layout = QVBoxLayout()
        main_layout.setSpacing(10)  # Aumentar espacio entre elementos

        # Panel superior - Búsqueda y selección
        top_panel = QWidget()
        top_layout = QHBoxLayout()
        top_layout.setSpacing(15)  # Aumentar espacio entre elementos

        # Panel izquierdo - Selección de archivos
        files_panel = QWidget()
        files_layout = QVBoxLayout()

        files_label = QLabel("Archivos a renombrar:")
        files_label.setFont(QFont("Arial", 10, QFont.Bold))

        self.files_list = QListWidget()

        files_buttons_layout = QHBoxLayout()
        self.add_files_button = QPushButton("Añadir archivos")
        self.add_folder_button = QPushButton("Añadir carpeta")
        self.clear_files_button = QPushButton("Limpiar lista")

        files_buttons_layout.addWidget(self.add_files_button)
        files_buttons_layout.addWidget(self.add_folder_button)
        files_buttons_layout.addWidget(self.clear_files_button)

        files_layout.addWidget(files_label)
        files_layout.addWidget(self.files_list)
        files_layout.addLayout(files_buttons_layout)

        # Directorio base para mover los archivos
        base_dir_group = QGroupBox("Directorio base para organizar")
        base_dir_layout = QHBoxLayout()

        self.base_dir_input = QLineEdit()
        self.base_dir_input.setPlaceholderText("Selecciona un directorio base (opcional)")
        self.base_dir_button = QPushButton("Explorar...")

        base_dir_layout.addWidget(self.base_dir_input)
        base_dir_layout.addWidget(self.base_dir_button)

        base_dir_group.setLayout(base_dir_layout)
        files_layout.addWidget(base_dir_group)

        # Botón de configuración
        self.config_button = QPushButton("Configuración")
        self.config_button.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold;")
        files_layout.addWidget(self.config_button)

        files_panel.setLayout(files_layout)

        # Panel central - Búsqueda TMDB
        search_panel = QWidget()
        search_layout = QVBoxLayout()

        search_label = QLabel("Buscar en TMDB:")
        search_label.setFont(QFont("Arial", 10, QFont.Bold))

        search_type_layout = QHBoxLayout()
        self.search_type_combo = QComboBox()
        self.search_type_combo.addItem("Series", "tv")
        self.search_type_combo.addItem("Películas", "movie")
        search_type_layout.addWidget(QLabel("Tipo:"))
        search_type_layout.addWidget(self.search_type_combo)
        search_type_layout.addStretch()

        search_term_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_button = QPushButton("Buscar")
        search_term_layout.addWidget(QLabel("Nombre:"))
        search_term_layout.addWidget(self.search_input)
        search_term_layout.addWidget(self.search_button)

        # Dividir el panel de búsqueda en resultados y vista previa
        search_results_layout = QHBoxLayout()

        # Lista de resultados (lado izquierdo)
        results_layout = QVBoxLayout()
        results_label = QLabel("Resultados:")
        self.search_results = QListWidget()
        results_layout.addWidget(results_label)
        results_layout.addWidget(self.search_results)

        # Vista previa del póster (lado derecho)
        poster_layout = QVBoxLayout()
        poster_label = QLabel("Póster:")

        self.poster_preview = QLabel("Selecciona un resultado para ver el póster")
        self.poster_preview.setAlignment(Qt.AlignCenter)
        self.poster_preview.setMinimumSize(200, 300)
        self.poster_preview.setMaximumSize(200, 300)
        self.poster_preview.setStyleSheet("border: 1px solid #CCCCCC; background-color: #F0F0F0;")
        self.poster_preview.setScaledContents(True)

        poster_layout.addWidget(poster_label)
        poster_layout.addWidget(self.poster_preview)
        poster_layout.addStretch()

        # Añadir layouts al panel de resultados
        search_results_layout.addLayout(results_layout, 3)
        search_results_layout.addLayout(poster_layout, 1)

        # Checkbox para detectar todas las temporadas
        self.detect_all_seasons_checkbox = QCheckBox("Detectar automáticamente todas las temporadas")
        self.detect_all_seasons_checkbox.setChecked(False)

        # Para series, añadir selección de temporada
        self.season_layout = QHBoxLayout()
        self.season_label = QLabel("Temporada:")
        self.season_combo = QComboBox()
        self.season_layout.addWidget(self.season_label)
        self.season_layout.addWidget(self.season_combo)
        self.season_layout.addStretch()

        # Opción para organizar en carpetas de temporadas
        self.organize_seasons_checkbox = QCheckBox("Organizar en carpetas de temporadas")
        self.organize_seasons_checkbox.setChecked(True)

        search_layout.addWidget(search_label)
        search_layout.addLayout(search_type_layout)
        search_layout.addLayout(search_term_layout)
        search_layout.addLayout(search_results_layout)
        search_layout.addWidget(self.detect_all_seasons_checkbox)
        search_layout.addLayout(self.season_layout)
        search_layout.addWidget(self.organize_seasons_checkbox)

        search_panel.setLayout(search_layout)

        # Añadir paneles al panel superior
        top_layout.addWidget(files_panel)
        top_layout.addWidget(search_panel)
        top_panel.setLayout(top_layout)

        # Panel central - Previsualización
        preview_panel = QWidget()
        preview_layout = QVBoxLayout()

        preview_label = QLabel("Previsualización de cambios:")
        preview_label.setFont(QFont("Arial", 10, QFont.Bold))

        # Crear TabWidget para mostrar diferentes vistas de previsualización
        self.preview_tabs = QTabWidget()

        # Tab 1: Vista tradicional de lista
        list_view_tab = QWidget()
        list_view_layout = QVBoxLayout(list_view_tab)

        preview_files_layout = QHBoxLayout()

        # Lista original
        original_layout = QVBoxLayout()
        original_label = QLabel("Nombre original:")
        self.original_list = QListWidget()
        original_layout.addWidget(original_label)
        original_layout.addWidget(self.original_list)

        # Lista nueva
        new_layout = QVBoxLayout()
        new_label = QLabel("Nuevo nombre:")
        self.new_list = QListWidget()
        new_layout.addWidget(new_label)
        new_layout.addWidget(self.new_list)

        preview_files_layout.addLayout(original_layout)
        preview_files_layout.addLayout(new_layout)
        list_view_layout.addLayout(preview_files_layout)

        # Tab 2: Vista de episodios por temporada
        self.episodes_season_view = EpisodesBySeasonView()

        # Añadir las pestañas al TabWidget
        self.preview_tabs.addTab(list_view_tab, "Vista de Lista")
        self.preview_tabs.addTab(self.episodes_season_view, "Vista por Temporadas")

        preview_layout.addWidget(preview_label)
        preview_layout.addWidget(self.preview_tabs)

        preview_panel.setLayout(preview_layout)

        # Panel inferior - Acciones
        bottom_panel = QWidget()
        bottom_layout = QHBoxLayout()

        self.rename_button = QPushButton("Renombrar archivos")
        self.rename_button.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; padding: 10px;")
        self.rename_button.setEnabled(False)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)

        bottom_layout.addWidget(self.rename_button)
        bottom_layout.addWidget(self.progress_bar)

        bottom_panel.setLayout(bottom_layout)

        # Añadir todos los paneles al layout principal
        main_layout.addWidget(top_panel, 3)
        main_layout.addWidget(preview_panel, 4)  # Aumentar proporción del panel de vista previa
        main_layout.addWidget(bottom_panel, 1)

        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)

        # Conectar eventos
        self.add_files_button.clicked.connect(self.add_files)
        self.add_folder_button.clicked.connect(self.add_folder)
        self.clear_files_button.clicked.connect(self.clear_files)
        self.base_dir_button.clicked.connect(self.select_base_directory)
        self.config_button.clicked.connect(self.show_config_dialog)
        self.search_button.clicked.connect(self.search_tmdb)
        self.search_results.itemClicked.connect(self.select_media)
        self.search_results.itemDoubleClicked.connect(self.show_poster_preview)
        self.season_combo.currentIndexChanged.connect(self.load_season_episodes)
        self.rename_button.clicked.connect(self.rename_files)
        self.search_type_combo.currentIndexChanged.connect(self.toggle_media_type)
        self.detect_all_seasons_checkbox.stateChanged.connect(self.toggle_detect_all_seasons)
        self.preview_tabs.currentChanged.connect(self.on_preview_tab_changed)

        # Inicialmente, ocultar la selección de temporada
        self.toggle_media_type()

    def closeEvent(self, event):
        """Manejador del evento de cierre de la ventana"""
        # Detener todos los hilos antes de cerrar
        self.stop_all_threads()
        event.accept()

    def stop_all_threads(self):
        """Detener todos los hilos en ejecución"""
        if self.search_worker and self.search_worker.isRunning():
            self.search_worker.stop()

        if self.episodes_fetcher and self.episodes_fetcher.isRunning():
            self.episodes_fetcher.stop()

        if self.all_seasons_fetcher and self.all_seasons_fetcher.isRunning():
            self.all_seasons_fetcher.stop()

        # Limpiar cualquier gestor de red en uso
        if self.network_manager:
            try:
                # Desconectar solo si hay conexiones
                if self.network_manager.receivers(self.network_manager.finished) > 0:
                    self.network_manager.finished.disconnect()
            except Exception as e:
                print(f"Error al desconectar señal en cierre: {e}")
            self.network_manager = None

    def select_base_directory(self):
        """Seleccionar directorio base para mover los archivos"""
        directory = QFileDialog.getExistingDirectory(self, "Seleccionar directorio base")
        if directory:
            self.base_directory = directory
            self.base_dir_input.setText(directory)

    def toggle_media_type(self):
        """Cambiar entre modo película y serie"""
        self.selected_media_type = self.search_type_combo.currentData()
        is_tv = self.selected_media_type == "tv"

        # Mostrar/ocultar elementos relacionados con series
        self.season_label.setVisible(is_tv)
        self.season_combo.setVisible(is_tv)
        self.organize_seasons_checkbox.setVisible(is_tv)
        self.detect_all_seasons_checkbox.setVisible(is_tv)

        # Mostrar/ocultar pestaña de temporadas según el tipo
        self.preview_tabs.setTabVisible(1, is_tv)  # Índice 1 es la pestaña de temporadas

        # Si cambiamos a película, asegurarse de mostrar la vista de lista
        if not is_tv:
            self.preview_tabs.setCurrentIndex(0)

        # Limpiar resultados anteriores
        self.search_results.clear()
        self.season_combo.clear()
        self.original_list.clear()
        self.new_list.clear()
        self.episodes_season_view.clear()  # Limpiar la vista de temporadas
        self.current_media_info = None
        self.episodes_info = {}
        self.all_seasons_info = {}
        self.update_rename_button()

    def toggle_detect_all_seasons(self, state):
        """Cambiar entre detectar una o todas las temporadas"""
        self.detect_all_seasons = state == Qt.Checked
        self.season_combo.setEnabled(not self.detect_all_seasons)

        # Si tenemos información de media y cambiamos este estado, actualizar la previsualización
        if self.current_media_info:
            if self.detect_all_seasons and not self.all_seasons_info:
                # Cargar datos de todas las temporadas si no lo hemos hecho ya
                self.load_all_seasons()
            else:
                # Actualizar la previsualización con la configuración actual
                self.update_preview()

    def on_preview_tab_changed(self, index):
        """Manejar el cambio de pestaña en la previsualización"""
        # Si cambiamos a la pestaña de temporadas (índice 1) y es una serie
        if index == 1 and self.selected_media_type == "tv":
            # Asegurarse de que la vista de temporadas esté actualizada
            self.update_preview()

            # Si no hay temporadas detectadas, pero tenemos archivos, intentar detectarlas
            if not self.episodes_season_view.episodes_by_season and self.files_to_rename:
                # Si no estamos ya en modo detección automática, activarlo temporalmente
                if not self.detect_all_seasons and self.current_media_info:
                    QMessageBox.information(self, "Detección de temporadas",
                        "Se activará temporalmente la detección automática de temporadas para organizar los episodios.")

                    self.detect_all_seasons_checkbox.setChecked(True)

    def show_poster_preview(self, item):
        """Mostrar el póster original de la serie o película seleccionada"""
        if not item:
            return

        media_info = item.data(Qt.UserRole)
        if not media_info:
            return

        # Obtener la ruta del póster
        poster_path = media_info.get("poster_path")

        # Obtener el título
        if self.selected_media_type == "tv":
            title = media_info.get("name", "")
        else:
            title = media_info.get("title", "")

        # Mostrar el diálogo con el póster
        dialog = PosterPreviewDialog(self, poster_path, title)
        dialog.exec_()

    def add_files(self):
        """Añadir archivos individuales"""
        files, _ = QFileDialog.getOpenFileNames(
            self, "Seleccionar archivos", "",
            "Archivos de vídeo (*.mp4 *.mkv *.avi *.mov *.wmv);;Todos los archivos (*)"
        )

        if files:
            self.process_files(files)

    def add_folder(self):
        """Añadir todos los archivos de vídeo de una carpeta y subcarpetas"""
        folder = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta")

        if folder:
            video_files = []

            # Función recursiva para buscar archivos en todas las subcarpetas
            def find_video_files(directory):
                for root, dirs, files in os.walk(directory):
                    for file in files:
                        if file.lower().endswith(('.mp4', '.mkv', '.avi', '.mov', '.wmv')):
                            video_files.append(os.path.join(root, file))

            # Iniciar búsqueda recursiva
            find_video_files(folder)

            if video_files:
                self.process_files(video_files)
                QMessageBox.information(self, "Información", f"Se encontraron {len(video_files)} archivos de vídeo.")
            else:
                QMessageBox.information(self, "Información", "No se encontraron archivos de vídeo en la carpeta seleccionada.")

    def process_files(self, files):
        """Procesar archivos añadidos"""
        for file_path in files:
            if file_path not in self.files_to_rename:
                self.files_to_rename.append(file_path)
                self.files_list.addItem(os.path.basename(file_path))

        self.update_preview()

    def clear_files(self):
        """Limpiar la lista de archivos"""
        self.files_list.clear()
        self.files_to_rename = []
        self.update_preview()

    def search_tmdb(self):
        """Buscar en TMDB"""
        search_term = self.search_input.text().strip()
        if not search_term:
            QMessageBox.warning(self, "Advertencia", "Por favor, introduce un término de búsqueda.")
            return

        self.search_results.clear()
        self.search_results.addItem("Buscando...")

        # Detener cualquier búsqueda anterior en curso
        if self.search_worker and self.search_worker.isRunning():
            self.search_worker.stop()

        # Iniciar búsqueda en un hilo separado
        self.search_worker = TMDBSearchWorker(search_term, self.selected_media_type)
        self.search_worker.finished.connect(self.display_search_results)
        self.search_worker.start()

    def display_search_results(self, results):
        """Mostrar resultados de búsqueda"""
        self.search_results.clear()

        if not results:
            self.search_results.addItem("No se encontraron resultados.")
            return

        for result in results:
            title = result.get("name", "") if self.selected_media_type == "tv" else result.get("title", "")
            year = ""

            if self.selected_media_type == "tv":
                first_air_date = result.get("first_air_date", "")
                if first_air_date:
                    year = f" ({first_air_date[:4]})"
            else:
                release_date = result.get("release_date", "")
                if release_date:
                    year = f" ({release_date[:4]})"

            item_text = f"{title}{year}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, result)
            self.search_results.addItem(item)

    def select_media(self, item):
        """Seleccionar serie o película de los resultados"""
        self.current_media_info = item.data(Qt.UserRole)

        # Mostrar el póster de la selección
        poster_path = self.current_media_info.get("poster_path")
        if poster_path:
            self.load_poster_preview(poster_path)
        else:
            # Si no hay póster, mostrar un mensaje
            self.poster_preview.setText("No hay póster disponible")
            self.poster_preview.setPixmap(QPixmap())  # Limpiar cualquier imagen anterior

        if self.selected_media_type == "tv":
            # Cargar temporadas disponibles
            self.season_combo.clear()
            num_seasons = self.current_media_info.get("number_of_seasons", 0)
            if num_seasons == 0:
                # Obtener información completa de la serie
                try:
                    series_id = self.current_media_info.get("id")
                    url = f"{TMDB_BASE_URL}/tv/{series_id}"
                    params = {"api_key": TMDB_API_KEY, "language": "es-ES"}
                    response = requests.get(url, params=params)
                    data = response.json()
                    num_seasons = data.get("number_of_seasons", 0)
                    self.current_media_info["number_of_seasons"] = num_seasons
                except Exception as e:
                    print(f"Error al obtener información de la serie: {e}")

            for i in range(1, num_seasons + 1):
                self.season_combo.addItem(f"Temporada {i}", i)

            # Si está marcado para detectar todas las temporadas, cargarlas
            if self.detect_all_seasons:
                self.load_all_seasons()
            else:
                # Cargar episodios de la primera temporada
                if self.season_combo.count() > 0:
                    self.load_season_episodes()
        else:
            # Para películas, actualizar directamente la previsualización
            self.update_preview()

    def load_poster_preview(self, poster_path):
        """Cargar la vista previa del póster en la interfaz principal"""
        if not poster_path:
            self.poster_preview.setText("No hay póster disponible")
            return

        poster_url = f"{TMDB_IMAGE_BASE_URL}{poster_path}"

        # Crear un gestor de red para descargar la imagen (limpiar cualquier solicitud anterior)
        if self.network_manager:
            try:
                # Desconectar solo si hay conexiones
                if self.network_manager.receivers(self.network_manager.finished) > 0:
                    self.network_manager.finished.disconnect()
            except Exception as e:
                print(f"Error al desconectar señal: {e}")

        self.network_manager = QNetworkAccessManager()
        self.network_manager.finished.connect(self.handle_poster_response)

        # Iniciar la descarga
        request = QNetworkRequest(QUrl(poster_url))
        self.network_manager.get(request)

    def handle_poster_response(self, reply):
        """Manejar la respuesta de red para la descarga del póster en la vista previa"""
        if reply.error() == QNetworkReply.NoError:
            data = reply.readAll()
            pixmap = QPixmap()
            pixmap.loadFromData(data)

            # Escalar la imagen para que se ajuste al tamaño del label manteniendo la proporción
            self.poster_preview.setPixmap(pixmap)
        else:
            self.poster_preview.setText("Error al cargar el póster")

        reply.deleteLater()

    def load_season_episodes(self):
        """Cargar episodios de la temporada seleccionada"""
        if not self.current_media_info or self.season_combo.count() == 0:
            return

        series_id = self.current_media_info.get("id")
        season_number = self.season_combo.currentData()

        # Detener cualquier carga anterior en curso
        if self.episodes_fetcher and self.episodes_fetcher.isRunning():
            self.episodes_fetcher.stop()

        # Iniciar carga en un hilo separado
        self.episodes_fetcher = SeasonEpisodesFetcher(series_id, season_number)
        self.episodes_fetcher.finished.connect(self.update_episodes_info)
        self.episodes_fetcher.start()

    def load_all_seasons(self):
        """Cargar episodios de todas las temporadas"""
        if not self.current_media_info:
            return

        series_id = self.current_media_info.get("id")
        num_seasons = self.current_media_info.get("number_of_seasons", 0)

        if num_seasons == 0:
            return

        # Detener cualquier carga anterior en curso
        if self.all_seasons_fetcher and self.all_seasons_fetcher.isRunning():
            self.all_seasons_fetcher.stop()

        # Iniciar carga en un hilo separado
        self.all_seasons_fetcher = AllSeasonsFetcher(series_id, num_seasons)
        self.all_seasons_fetcher.finished.connect(self.update_all_seasons_info)
        self.all_seasons_fetcher.start()

    def update_episodes_info(self, episodes_dict):
        """Actualizar información de episodios"""
        self.episodes_info = episodes_dict
        self.update_preview()

    def update_all_seasons_info(self, all_seasons_dict):
        """Actualizar información de todas las temporadas"""
        self.all_seasons_info = all_seasons_dict
        self.update_preview()

    def update_preview(self):
        """Actualizar previsualización de renombres"""
        self.original_list.clear()
        self.new_list.clear()
        self.new_filenames = []

        if not self.files_to_rename or not self.current_media_info:
            self.update_rename_button()
            # Limpiar también la vista por temporadas
            self.episodes_season_view.clear()
            return

        # Obtener el título base
        if self.selected_media_type == "tv":
            title = self.current_media_info.get("name", "")
        else:
            title = self.current_media_info.get("title", "")

        # Para agrupar episodios por temporada en la nueva vista
        episodes_by_season = {}

        for file_path in self.files_to_rename:
            file_name = os.path.basename(file_path)
            self.original_list.addItem(file_name)

            # Generar nuevo nombre según el tipo
            if self.selected_media_type == "tv":
                if self.detect_all_seasons:
                    new_name, season_num, episode_num = self.generate_tv_filename_auto_season(file_path, title, return_numbers=True)
                else:
                    season_number = self.season_combo.currentData() if self.season_combo.count() > 0 else None
                    if season_number is None:
                        new_name = file_name  # Mantener el nombre original si no hay temporada seleccionada
                        season_num = None
                        episode_num = None
                    else:
                        new_name, episode_num = self.generate_tv_filename(file_name, title, season_number, return_episode=True)
                        season_num = season_number
            else:
                new_name = self.generate_movie_filename(file_name, title)
                season_num = None
                episode_num = None

            self.new_filenames.append(new_name)
            self.new_list.addItem(new_name)

            # Para series, organizar por temporada para la vista alternativa
            if self.selected_media_type == "tv" and season_num is not None and episode_num is not None:
                if season_num not in episodes_by_season:
                    episodes_by_season[season_num] = {}

                if episode_num not in episodes_by_season[season_num]:
                    episodes_by_season[season_num][episode_num] = []

                episodes_by_season[season_num][episode_num].append((file_path, new_name))

        # Actualizar la vista por temporadas si hay episodios de series
        if self.selected_media_type == "tv" and episodes_by_season:
            self.episodes_season_view.set_episodes(episodes_by_season)
            # Si es serie, mostrar automáticamente la pestaña de temporadas
            self.preview_tabs.setCurrentIndex(1)
        else:
            # Para películas o si no hay información de temporadas, mostrar la vista de lista y limpiar la otra
            self.episodes_season_view.clear()
            self.preview_tabs.setCurrentIndex(0)

        self.update_rename_button()

    def generate_tv_filename(self, file_name, series_title, season_number, return_episode=False):
        """Generar nombre para episodios de serie con temporada específica"""
        # Intentar extraer el número de episodio del nombre original
        episode_number = None

        # Patrones comunes para detectar temporada y episodio
        patterns = [
            r'[Ss](\d+)[Ee](\d+)',  # S01E01
            r'(\d+)x(\d+)',         # 1x01
            r'[Ee](\d+)',           # E01 (asume que la temporada ya se conoce)
            r'[Ee]pisode\s*(\d+)',  # Episode 01
            r'.*?(\d+)'             # Último recurso: buscar cualquier número
        ]

        for pattern in patterns:
            match = re.search(pattern, file_name)
            if match:
                if len(match.groups()) == 2:  # Patrón con temporada y episodio
                    # Ignoramos el número de temporada extraído y usamos el seleccionado
                    episode_number = int(match.group(2))
                else:  # Patrón solo con episodio
                    episode_number = int(match.group(1))
                break

        if episode_number is None:
            # Si no se puede detectar, usar un placeholder
            result = f"{series_title} S{season_number:02d}EXX.{file_name.split('.')[-1]}"
            return (result, None) if return_episode else result

        # Obtener el título del episodio si está disponible
        episode_title = self.episodes_info.get(episode_number, "")

        # Usar el formato seleccionado
        format_index = self.config["tv_format"]
        format_str = self.config["tv_formats"][format_index]

        # Formatear nombre según el formato seleccionado
        try:
            name_part = format_str.format(
                title=series_title,
                season=season_number,
                episode=episode_number,
                episode_title=episode_title
            )
        except KeyError:
            # Si hay algún error con el formato, usar el formato básico
            name_part = f"{series_title} S{season_number:02d}E{episode_number:02d}"
            if episode_title:
                name_part += f" {episode_title}"

        # Añadir extensión
        extension = file_name.split('.')[-1]
        result = f"{name_part}.{extension}"

        return (result, episode_number) if return_episode else result

    def generate_tv_filename_auto_season(self, file_path, series_title, return_numbers=False):
        """Generar nombre para episodios detectando automáticamente la temporada y episodio"""
        file_name = os.path.basename(file_path)

        # Patrones para detectar temporada y episodio
        patterns = [
            (r'[Ss](\d+)[Ee](\d+)', 1, 2),  # S01E01 - grupo 1 = temporada, grupo 2 = episodio
            (r'(\d+)x(\d+)', 1, 2),          # 1x01 - grupo 1 = temporada, grupo 2 = episodio
            (r'[Tt]emporada\s*(\d+).*?[Ee]pisodio\s*(\d+)', 1, 2),  # Temporada 1 Episodio 1
            (r'[Tt]emporada\s*(\d+).*?[Ee]p\s*(\d+)', 1, 2),        # Temporada 1 Ep 1
            (r'[Tt](\d+)[Ee](\d+)', 1, 2),   # T1E01
            (r'.*?(\d)[.](\d+)', 1, 2)       # Serie.1.01 o similar
        ]

        # Intentar extraer temporada y episodio con los patrones
        season_number = None
        episode_number = None

        for pattern, season_group, episode_group in patterns:
            match = re.search(pattern, file_name)
            if match:
                try:
                    season_number = int(match.group(season_group))
                    episode_number = int(match.group(episode_group))
                    break
                except (IndexError, ValueError):
                    continue

        # Si no se detectó con los patrones, intentar extraer del nombre del directorio
        if season_number is None:
            dir_name = os.path.basename(os.path.dirname(file_path))
            season_match = re.search(r'[Ss]eason\s*(\d+)|[Tt]emporada\s*(\d+)|[Ss](\d+)|[Tt](\d+)', dir_name)
            if season_match:
                # Tomar el primer grupo no vacío
                for group in season_match.groups():
                    if group:
                        season_number = int(group)
                        break

                # Intentar extraer solo el número de episodio del nombre del archivo
                ep_match = re.search(r'[Ee](\d+)|[Ee]pisode\s*(\d+)|[Ee]p\s*(\d+)|(\d+)', file_name)
                if ep_match:
                    for group in ep_match.groups():
                        if group:
                            episode_number = int(group)
                            break

        # Si aún no tenemos temporada o episodio, no podemos renombrar correctamente
        if season_number is None or episode_number is None:
            if return_numbers:
                return file_name, None, None
            return file_name  # Mantener el nombre original

        # Verificar que la temporada y el episodio estén en el rango
        if season_number not in self.all_seasons_info:
            if return_numbers:
                return file_name, None, None
            return file_name  # Mantener el nombre original si la temporada no existe

        # Obtener el título del episodio si está disponible
        episode_title = ""
        if episode_number in self.all_seasons_info[season_number]:
            episode_title = self.all_seasons_info[season_number][episode_number]

        # Usar el formato seleccionado
        format_index = self.config["tv_format"]
        format_str = self.config["tv_formats"][format_index]

        # Formatear nombre según el formato seleccionado
        try:
            name_part = format_str.format(
                title=series_title,
                season=season_number,
                episode=episode_number,
                episode_title=episode_title
            )
        except KeyError:
            # Si hay algún error con el formato, usar el formato básico
            name_part = f"{series_title} S{season_number:02d}E{episode_number:02d}"
            if episode_title:
                name_part += f" {episode_title}"

        # Añadir extensión
        extension = file_name.split('.')[-1]
        result = f"{name_part}.{extension}"

        if return_numbers:
            return result, season_number, episode_number
        return result

    def generate_movie_filename(self, file_name, movie_title):
        """Generar nombre para películas"""
        # Extraer el año de lanzamiento
        release_date = self.current_media_info.get("release_date", "")
        year = release_date[:4] if release_date else ""

        # Usar el formato seleccionado
        format_index = self.config["movie_format"]
        format_str = self.config["movie_formats"][format_index]

        # Formatear nombre según el formato seleccionado
        try:
            name_part = format_str.format(
                title=movie_title,
                year=year
            )
        except KeyError:
            # Si hay algún error con el formato, usar el formato básico
            name_part = f"{movie_title} ({year})" if year else movie_title

        # Obtener la extensión del archivo
        extension = file_name.split('.')[-1]

        # Formatear el nombre final
        return f"{name_part}.{extension}"

    def update_rename_button(self):
        """Actualizar estado del botón de renombrar"""
        enable = (len(self.files_to_rename) > 0 and
                 self.current_media_info is not None and
                 len(self.new_filenames) == len(self.files_to_rename))

        self.rename_button.setEnabled(enable)

    def rename_files(self):
        """Renombrar los archivos y organizarlos en carpetas de temporadas si es necesario"""
        if not self.files_to_rename or not self.new_filenames:
            return

        self.progress_bar.setRange(0, len(self.files_to_rename))
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)

        success_count = 0
        error_files = []

        # Para organizar series en carpetas de temporadas
        organize_seasons = self.organize_seasons_checkbox.isChecked() and self.selected_media_type == "tv"
        # Para organizar películas en carpetas
        organize_movies = self.config["organize_movies"] and self.selected_media_type == "movie"
        # Descargar pósters
        download_posters = self.config["download_posters"]

        # Base del nombre para la carpeta principal (título + año)
        main_folder_name = ""
        poster_path = ""

        if self.selected_media_type == "tv":
            title = self.current_media_info.get("name", "")
            first_air_date = self.current_media_info.get("first_air_date", "")
            year = f" ({first_air_date[:4]})" if first_air_date else ""
            main_folder_name = f"{title}{year}"
            poster_path = self.current_media_info.get("poster_path", "")
        else:
            title = self.current_media_info.get("title", "")
            release_date = self.current_media_info.get("release_date", "")
            year = f" ({release_date[:4]})" if release_date else ""
            main_folder_name = f"{title}{year}"
            poster_path = self.current_media_info.get("poster_path", "")

        # Determinar directorio base para la organización
        root_directory = self.base_directory if self.base_directory else os.path.dirname(self.files_to_rename[0])

        # Crear directorio principal si usamos directorio base o si organizamos películas
        if self.base_directory or organize_movies:
            main_folder_path = os.path.join(root_directory, main_folder_name)
            if not os.path.exists(main_folder_path):
                try:
                    os.makedirs(main_folder_path)
                except Exception as e:
                    QMessageBox.critical(
                        self, "Error",
                        f"No se pudo crear el directorio principal: {str(e)}"
                    )
                    return

            # Descargar póster si está activada la opción
            if download_posters and poster_path:
                self.download_poster(poster_path, main_folder_path)
        else:
            main_folder_path = root_directory

        # Diccionario para agrupar archivos por temporada (para mostrar visualmente)
        season_files = {}
        # Diccionario para la vista de temporadas
        episodes_by_season = {}

        for i, (old_path, new_name) in enumerate(zip(self.files_to_rename, self.new_filenames)):
            try:
                season_num = None
                episode_num = None

                # Determinar el directorio destino según las opciones
                if organize_seasons and self.selected_media_type == "tv":
                    # Extraer número de temporada del nuevo nombre
                    season_match = re.search(r'S(\d+)E(\d+)', new_name)
                    if season_match:
                        season_num = int(season_match.group(1))
                        episode_num = int(season_match.group(2))
                        # Crear directorio de temporada si no existe
                        season_dir = os.path.join(main_folder_path, f"Season {season_num:02d}")
                        if not os.path.exists(season_dir):
                            os.makedirs(season_dir)
                        new_path = os.path.join(season_dir, new_name)

                        # Agrupar por temporada para visualización
                        if season_num not in season_files:
                            season_files[season_num] = []
                        season_files[season_num].append(new_name)

                        # Agrupar para la vista de temporadas
                        if season_num not in episodes_by_season:
                            episodes_by_season[season_num] = {}
                        if episode_num not in episodes_by_season[season_num]:
                            episodes_by_season[season_num][episode_num] = []
                        episodes_by_season[season_num][episode_num].append((old_path, new_path))
                    else:
                        new_path = os.path.join(main_folder_path, new_name)
                elif organize_movies and self.selected_media_type == "movie":
                    # Para películas, mover directamente a la carpeta principal
                    new_path = os.path.join(main_folder_path, new_name)
                else:
                    new_path = os.path.join(main_folder_path, new_name)

                # Verificar si el archivo destino ya existe
                if os.path.exists(new_path) and old_path != new_path:
                    response = QMessageBox.question(
                        self, "Archivo existente",
                        f"El archivo '{new_name}' ya existe en la ruta destino. ¿Deseas sobrescribirlo?",
                        QMessageBox.Yes | QMessageBox.No | QMessageBox.YesToAll | QMessageBox.NoToAll
                    )

                    if response == QMessageBox.No:
                        error_files.append(f"{old_path} (archivo destino ya existe)")
                        continue

                # Crear directorios intermedios si no existen
                os.makedirs(os.path.dirname(new_path), exist_ok=True)

                # Usar shutil.move en lugar de os.rename para mover entre diferentes dispositivos/particiones
                shutil.move(old_path, new_path)
                success_count += 1
            except Exception as e:
                error_files.append(f"{old_path} ({str(e)})")

            self.progress_bar.setValue(i + 1)

        self.progress_bar.setVisible(False)

        # Si se reorganizaron archivos por temporada, mostrar un resumen y actualizar vista de temporadas
        if season_files and organize_seasons:
            # Actualizar la vista de temporadas con los archivos organizados
            if episodes_by_season:
                self.episodes_season_view.set_episodes(episodes_by_season)
                # Mostrar la pestaña de temporadas
                self.preview_tabs.setCurrentIndex(1)

            # Preparar el resumen para mostrarlo
            season_summary = "Archivos organizados por temporada:\n\n"
            for season, files in sorted(season_files.items()):
                season_summary += f"Temporada {season}:\n"
                for file in files:
                    season_summary += f"  - {file}\n"
                season_summary += "\n"

            # Mostrar resumen en un diálogo aparte
            summary_dialog = QDialog(self)
            summary_dialog.setWindowTitle("Resumen de organización")
            summary_dialog.setMinimumSize(500, 400)

            layout = QVBoxLayout()

            summary_text = QLabel(season_summary)
            summary_text.setAlignment(Qt.AlignLeft | Qt.AlignTop)

            scroll_area = QScrollArea()
            scroll_area.setWidget(summary_text)
            scroll_area.setWidgetResizable(True)

            layout.addWidget(scroll_area)

            close_button = QPushButton("Cerrar")
            close_button.clicked.connect(summary_dialog.accept)
            layout.addWidget(close_button, alignment=Qt.AlignRight)

            summary_dialog.setLayout(layout)
            summary_dialog.exec_()

        # Mostrar resumen
        if success_count == len(self.files_to_rename):
            QMessageBox.information(
                self, "Operación completada",
                f"Se han renombrado y movido correctamente {success_count} archivos."
            )
            # Limpiar las listas
            self.files_list.clear()
            self.original_list.clear()
            self.new_list.clear()
            self.files_to_rename = []
            self.new_filenames = []
            self.update_rename_button()
        else:
            error_message = "\n".join(error_files)
            QMessageBox.warning(
                self, "Operación con errores",
                f"Se han renombrado {success_count} de {len(self.files_to_rename)} archivos.\n\nErrores:\n{error_message}"
            )

    def download_poster(self, poster_path, destination_folder):
        """Descargar el póster y guardarlo en la carpeta destino"""
        if not poster_path:
            return False

        try:
            # Construir la URL del póster
            poster_url = f"{TMDB_IMAGE_BASE_URL}{poster_path}"

            # Nombre del archivo de póster
            poster_filename = "poster.jpg"

            # Ruta completa del póster
            poster_file_path = os.path.join(destination_folder, poster_filename)

            # Descargar la imagen
            response = requests.get(poster_url, stream=True)
            response.raise_for_status()  # Lanzar excepción si hay error HTTP

            # Guardar la imagen
            with open(poster_file_path, 'wb') as f:
                response.raw.decode_content = True
                shutil.copyfileobj(response.raw, f)

            print(f"Póster guardado en: {poster_file_path}")
            return True
        except Exception as e:
            print(f"Error al descargar el póster: {e}")
            return False

    def show_config_dialog(self):
        """Mostrar el diálogo de configuración"""
        dialog = ConfigDialog(self, self.config)
        if dialog.exec_() == QDialog.Accepted:
            self.config = dialog.get_config()
            # Actualizar la UI según la nueva configuración
            self.update_preview()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TMDBRenamer()
    window.show()
    sys.exit(app.exec_())
