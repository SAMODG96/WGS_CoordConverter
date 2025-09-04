# -*- coding: utf-8 -*-
from qgis.PyQt.QtCore import Qt, QVariant
from qgis.PyQt.QtWidgets import (QAction, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                                 QComboBox, QCheckBox, QDialogButtonBox,
                                 QProgressDialog, QMessageBox)
from qgis.PyQt.QtGui import QIcon
from qgis.core import (Qgis, QgsProject, QgsMapLayer, QgsCoordinateReferenceSystem,
                       QgsCoordinateTransform, QgsWkbTypes, QgsField, QgsFeature, QgsMessageLog)
from qgis.gui import QgsProjectionSelectionWidget

PLUGIN_MENU = "&WGS CoordConverter"
PLUGIN_TITLE = "WGS - Convertisseur de Coordonnées"

# --- Formatting options ---
DD_LENGTH = 24
DD_PRECISION = 10   # 10 chiffres après la virgule
DMS_LENGTH = 64
XY_LENGTH  = 24
XY_PRECISION = 3

AUTHOR_STR = "Auteur : OUEDRAOGO SALAM  |  Email : saam.odg@gmail.com  |  Contact : +225 0789431882"

def dd_to_dms(dd: float, is_lat: bool) -> str:
    if dd is None:
        return ""
    hemi = "N" if is_lat and dd >= 0 else "S" if is_lat else ("E" if dd >= 0 else "W")
    abs_dd = abs(dd)
    deg = int(abs_dd)
    min_float = (abs_dd - deg) * 60.0
    minute = int(min_float)
    sec = (min_float - minute) * 60.0
    deg_fmt = f"{deg:02d}" if is_lat else f"{deg:03d}"
    return f'{deg_fmt}°{minute:02d}\'{sec:05.2f}"{hemi}'

def ensure_field(layer, name, qvariant_type, length=0, precision=0):
    prov = layer.dataProvider()
    if layer.fields().indexOf(name) == -1:
        fld = QgsField(name, qvariant_type, '', length, precision)
        ok = prov.addAttributes([fld])
        if not ok:
            raise RuntimeError(f"Impossible d'ajouter le champ {name}")
        layer.updateFields()
    return layer.fields().indexOf(name)

def geometry_to_point(geom):
    if not geom or geom.isEmpty():
        return None
    if geom.type() == QgsWkbTypes.PointGeometry:
        if geom.isMultipart():
            pts = geom.asMultiPoint()
            if not pts:
                return None
            return pts[0]
        else:
            return geom.asPoint()
    return geom.centroid().asPoint()

def wkb_to_uri(wkb_type, crs):
    is_multi = QgsWkbTypes.isMultiType(wkb_type)
    gtype = QgsWkbTypes.geometryType(wkb_type)
    if gtype == QgsWkbTypes.PointGeometry:
        base = "MultiPoint" if is_multi else "Point"
    elif gtype == QgsWkbTypes.LineGeometry:
        base = "MultiLineString" if is_multi else "LineString"
    elif gtype == QgsWkbTypes.PolygonGeometry:
        base = "MultiPolygon" if is_multi else "Polygon"
    else:
        base = "Unknown"
    return f"{base}?crs={crs.authid()}"

class CoordConverterDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(PLUGIN_TITLE)
        self.setMinimumWidth(620)

        layout = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel("Couche :"))
        self.layer_combo = QComboBox()
        row.addWidget(self.layer_combo, 1)
        layout.addLayout(row)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("SCR d'origine :"))
        self.src_crs = QgsProjectionSelectionWidget()
        row2.addWidget(self.src_crs, 1)
        layout.addLayout(row2)

        self.chk_target = QCheckBox("Reprojeter vers un SCR cible (optionnel)")
        layout.addWidget(self.chk_target)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("SCR cible :"))
        self.tgt_crs = QgsProjectionSelectionWidget()
        self.tgt_crs.setEnabled(False)
        row3.addWidget(self.tgt_crs, 1)
        layout.addLayout(row3)

        self.chk_target.toggled.connect(self.tgt_crs.setEnabled)

        btns = QDialogButtonBox()
        self.btn_run = btns.addButton("Exécuter", QDialogButtonBox.AcceptRole)
        self.btn_close = btns.addButton("Fermer", QDialogButtonBox.RejectRole)
        layout.addWidget(btns)
        self.btn_run.clicked.connect(self.on_run)
        self.btn_close.clicked.connect(self.reject)

        footer = QLabel(AUTHOR_STR)
        footer.setWordWrap(True)
        footer.setStyleSheet("color: #6b7280; font-size: 11px;")
        layout.addWidget(footer)

        self.populate_layers()

    def populate_layers(self):
        self.layers = [lyr for lyr in QgsProject.instance().mapLayers().values() if lyr.type() == QgsMapLayer.VectorLayer]
        self.layer_combo.clear()
        for lyr in self.layers:
            self.layer_combo.addItem(lyr.name())
        if self.layers:
            self.layer_combo.setCurrentIndex(0)
            self.src_crs.setCrs(self.layers[0].crs())
        self.layer_combo.currentIndexChanged.connect(self._layer_changed)

    def _layer_changed(self, idx):
        if 0 <= idx < len(self.layers):
            self.src_crs.setCrs(self.layers[idx].crs())

    def on_run(self):
        idx = self.layer_combo.currentIndex()
        if idx < 0 or idx >= len(self.layers):
            QMessageBox.warning(self, PLUGIN_TITLE, "Veuillez choisir une couche.")
            return

        layer = self.layers[idx]
        srcCrs = self.src_crs.crs()
        if not srcCrs.isValid():
            QMessageBox.critical(self, PLUGIN_TITLE, "Le SCR d'origine n'est pas valide.")
            return

        toWgs = QgsCoordinateReferenceSystem("EPSG:4326")
        try:
            tf_wgs = QgsCoordinateTransform(srcCrs, toWgs, QgsProject.instance().transformContext())
        except Exception as e:
            QMessageBox.critical(self, PLUGIN_TITLE, f"Transformation vers WGS84 impossible : {e}")
            return

        use_target = self.chk_target.isChecked()
        tf_tgt = None
        tgtCrs = None
        if use_target:
            tgtCrs = self.tgt_crs.crs()
            if not tgtCrs.isValid():
                QMessageBox.critical(self, PLUGIN_TITLE, "Le SCR cible n'est pas valide.")
                return
            try:
                tf_tgt = QgsCoordinateTransform(srcCrs, tgtCrs, QgsProject.instance().transformContext())
            except Exception as e:
                QMessageBox.critical(self, PLUGIN_TITLE, f"Transformation vers le SCR cible impossible : {e}")
                return

        can_edit = layer.isEditable() or layer.startEditing()
        if can_edit:
            self._process_in_place(layer, tf_wgs, tf_tgt, use_target)
        else:
            self._process_to_new_layer(layer, srcCrs, tf_wgs, tf_tgt, use_target)

    def _process_in_place(self, layer, tf_wgs, tf_tgt, use_target):
        idx_lon_dd = ensure_field(layer, "lon_dd", QVariant.Double, length=DD_LENGTH, precision=DD_PRECISION)
        idx_lat_dd = ensure_field(layer, "lat_dd", QVariant.Double, length=DD_LENGTH, precision=DD_PRECISION)
        idx_lon_dms = ensure_field(layer, "lon_dms", QVariant.String, length=DMS_LENGTH, precision=0)
        idx_lat_dms = ensure_field(layer, "lat_dms", QVariant.String, length=DMS_LENGTH, precision=0)
        if use_target:
            idx_x_proj = ensure_field(layer, "x_proj", QVariant.Double, length=XY_LENGTH, precision=XY_PRECISION)
            idx_y_proj = ensure_field(layer, "y_proj", QVariant.Double, length=XY_LENGTH, precision=XY_PRECISION)

        feats = layer.getFeatures()
        total = layer.featureCount()
        prog = QProgressDialog("Conversion des coordonnées (dans la couche)...", "Annuler", 0, total, self)
        prog.setWindowTitle(PLUGIN_TITLE)
        prog.setWindowModality(Qt.WindowModal)
        prog.show()

        changed = False
        for i, f in enumerate(feats, start=1):
            if prog.wasCanceled():
                break
            geom = f.geometry()
            if not geom or geom.isEmpty():
                continue
            pt = geometry_to_point(geom)
            if pt is None:
                continue

            try:
                pt_wgs = tf_wgs.transform(pt)
                lon_dd = float(pt_wgs.x())
                lat_dd = float(pt_wgs.y())
                lon_dms = dd_to_dms(lon_dd, is_lat=False)
                lat_dms = dd_to_dms(lat_dd, is_lat=True)

                updates = {
                    idx_lon_dd: lon_dd,
                    idx_lat_dd: lat_dd,
                    idx_lon_dms: lon_dms,
                    idx_lat_dms: lat_dms
                }
                if use_target and tf_tgt:
                    pt_tgt = tf_tgt.transform(pt)
                    updates[idx_x_proj] = float(pt_tgt.x())
                    updates[idx_y_proj] = float(pt_tgt.y())

                for fld_idx, val in updates.items():
                    layer.changeAttributeValue(f.id(), fld_idx, val)
                changed = True
            except Exception as ge:
                QgsMessageLog.logMessage(f"Echec sur l'FID {f.id()}: {ge}", "WGS CoordConverter", Qgis.Warning)

            if i % 50 == 0:
                prog.setValue(i)
        prog.setValue(total)

        if changed:
            if not layer.commitChanges():
                layer.rollBack()
                QMessageBox.critical(self, PLUGIN_TITLE, "Echec lors de l'enregistrement des modifications.")
            else:
                QMessageBox.information(self, PLUGIN_TITLE, "Terminé ! Les champs ont été mis à jour dans la couche.")
        else:
            layer.rollBack()
            QMessageBox.information(self, PLUGIN_TITLE, "Aucune modification appliquée.")

    def _process_to_new_layer(self, layer, srcCrs, tf_wgs, tf_tgt, use_target):
        from qgis.core import QgsVectorLayer

        uri = wkb_to_uri(layer.wkbType(), srcCrs)
        new_name = f"{layer.name()}_CoordConv"
        new_layer = QgsVectorLayer(uri, new_name, "memory")
        prov_new = new_layer.dataProvider()

        # Copy original fields
        orig_fields = layer.fields()
        prov_new.addAttributes([fld for fld in orig_fields])
        new_layer.updateFields()

        def add_calc_field(name, vtype, length=0, precision=0):
            from qgis.core import QgsField
            prov_new.addAttributes([QgsField(name, vtype, '', length, precision)])
            new_layer.updateFields()
            return new_layer.fields().indexOf(name)

        idx_lon_dd = add_calc_field("lon_dd", QVariant.Double, DD_LENGTH, DD_PRECISION)
        idx_lat_dd = add_calc_field("lat_dd", QVariant.Double, DD_LENGTH, DD_PRECISION)
        idx_lon_dms = add_calc_field("lon_dms", QVariant.String, DMS_LENGTH, 0)
        idx_lat_dms = add_calc_field("lat_dms", QVariant.String, DMS_LENGTH, 0)
        idx_x_proj = idx_y_proj = None
        if use_target:
            idx_x_proj = add_calc_field("x_proj", QVariant.Double, XY_LENGTH, XY_PRECISION)
            idx_y_proj = add_calc_field("y_proj", QVariant.Double, XY_LENGTH, XY_PRECISION)

        feats = layer.getFeatures()
        total = layer.featureCount()
        prog = QProgressDialog("Conversion des coordonnées (nouvelle couche)...", "Annuler", 0, total, self)
        prog.setWindowTitle(PLUGIN_TITLE)
        prog.setWindowModality(Qt.WindowModal)
        prog.show()

        new_feats = []
        for i, f in enumerate(feats, start=1):
            if prog.wasCanceled():
                break
            geom = f.geometry()
            if not geom or geom.isEmpty():
                continue
            pt = geometry_to_point(geom)
            if pt is None:
                continue

            try:
                pt_wgs = tf_wgs.transform(pt)
                lon_dd = float(pt_wgs.x())
                lat_dd = float(pt_wgs.y())
                lon_dms = dd_to_dms(lon_dd, is_lat=False)
                lat_dms = dd_to_dms(lat_dd, is_lat=True)

                attr_vals = list(f.attributes())
                while len(attr_vals) < new_layer.fields().count():
                    attr_vals.append(None)

                attr_vals[idx_lon_dd] = lon_dd
                attr_vals[idx_lat_dd] = lat_dd
                attr_vals[idx_lon_dms] = lon_dms
                attr_vals[idx_lat_dms] = lat_dms

                if use_target and tf_tgt is not None and idx_x_proj is not None and idx_y_proj is not None:
                    pt_tgt = tf_tgt.transform(pt)
                    attr_vals[idx_x_proj] = float(pt_tgt.x())
                    attr_vals[idx_y_proj] = float(pt_tgt.y())

                nf = QgsFeature(new_layer.fields())
                nf.setGeometry(geom)
                nf.setAttributes(attr_vals)
                new_feats.append(nf)
            except Exception as ge:
                QgsMessageLog.logMessage(f"Echec sur l'FID {f.id()}: {ge}", "WGS CoordConverter", Qgis.Warning)

            if i % 50 == 0:
                prog.setValue(i)
        prog.setValue(total)

        if new_feats:
            prov_new.addFeatures(new_feats)
        new_layer.updateExtents()
        QgsProject.instance().addMapLayer(new_layer)
        QMessageBox.information(self, PLUGIN_TITLE, f"Source non éditable : nouvelle couche « {new_name} » créée.")

class WGSCoordConverterPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None

    def initGui(self):
        import os
        icon_path = os.path.join(os.path.dirname(__file__), "icon.svg")
        self.action = QAction(QIcon(icon_path), PLUGIN_TITLE, self.iface.mainWindow())
        self.action.setToolTip("Convertir DD → DMS et calculer X/Y projetés (fallback nouvelle couche si non éditable)")
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu(PLUGIN_MENU, self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        if self.action:
            self.iface.removePluginMenu(PLUGIN_MENU, self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action = None

    def run(self):
        dlg = CoordConverterDialog(self.iface.mainWindow())
        dlg.exec_()
