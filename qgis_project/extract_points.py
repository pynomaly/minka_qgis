import os
from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsVectorFileWriter,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsField,
    QgsCoordinateTransform,
)
from qgis.PyQt.QtWidgets import QInputDialog
from qgis.PyQt.QtCore import QVariant

# ── Layer selection dialogs ──────────────────────────────────────────────
available_layers = [
    layer.name()
    for layer in QgsProject.instance().mapLayers().values()
    if isinstance(layer, QgsVectorLayer)
]

if len(available_layers) < 2:
    print("Need at least 2 vector layers")
else:
    # Select source layer (coast/polygon layer to extract vertices from)
    source_name, ok1 = QInputDialog.getItem(
        None,
        "Source layer",
        "Select the polygon layer to extract vertices from:",
        available_layers,
        0,
        False,
    )

    if not ok1:
        print("Cancelled")
    else:
        # Select filter layer (polygon that defines the area)
        filter_name, ok2 = QInputDialog.getItem(
            None,
            "Filter layer",
            "Select the polygon layer that defines the area:",
            available_layers,
            0,
            False,
        )

        if not ok2:
            print("Cancelled")
        else:
            source_layer = QgsProject.instance().mapLayersByName(source_name)[0]
            filter_layer = QgsProject.instance().mapLayersByName(filter_name)[0]

            # ── Debug info ────────────────────────────────────────────────
            print(f"Source layer: {source_name}")
            print(f"  CRS: {source_layer.crs().authid()}")
            print(f"  Features: {source_layer.featureCount()}")
            print(f"  Geometry type: {source_layer.geometryType()}")

            print(f"Filter layer: {filter_name}")
            print(f"  CRS: {filter_layer.crs().authid()}")
            print(f"  Features: {filter_layer.featureCount()}")
            print(f"  Geometry type: {filter_layer.geometryType()}")

            # ── 1. Get filter geometry and transform if needed ───────────
            filter_geoms = []
            transform = None

            if source_layer.crs() != filter_layer.crs():
                print("Transforming filter layer coordinates...")
                transform = QgsCoordinateTransform(
                    filter_layer.crs(),
                    source_layer.crs(),
                    QgsProject.instance(),
                )

            for f in filter_layer.getFeatures():
                geom = QgsGeometry(f.geometry())
                if transform:
                    geom.transform(transform)
                filter_geoms.append(geom)

            filter_geom = QgsGeometry.unaryUnion(filter_geoms)
            print(f"Filter geometry valid: {filter_geom.isGeosValid()}")
            print(f"Filter geometry area: {filter_geom.area()}")

            # ── 2. Create point layer ─────────────────────────────────────
            point_layer = QgsVectorLayer(
                f"Point?crs={source_layer.crs().authid()}",
                "extracted_points",
                "memory",
            )
            point_provider = point_layer.dataProvider()

            point_provider.addAttributes([
                QgsField("id", QVariant.Int),
                QgsField("x", QVariant.Double),
                QgsField("y", QVariant.Double),
                QgsField("source_id", QVariant.Int),
            ])
            point_layer.updateFields()

            # ── 3. Extract vertices within filter area ────────────────────
            point_id = 0
            for feature in source_layer.getFeatures():
                geom = feature.geometry()
                if geom.isMultipart():
                    polygons = geom.asMultiPolygon()
                else:
                    polygons = [geom.asPolygon()]

                for polygon in polygons:
                    for ring in polygon:
                        for vertex in ring:
                            pt = QgsPointXY(vertex)
                            pt_geom = QgsGeometry.fromPointXY(pt)
                            if filter_geom.intersects(pt_geom):
                                point_id += 1
                                new_feature = QgsFeature(point_layer.fields())
                                new_feature.setGeometry(pt_geom)
                                new_feature.setAttributes([
                                    point_id,
                                    pt.x(),
                                    pt.y(),
                                    feature.id(),
                                ])
                                point_provider.addFeature(new_feature)

            # ── 4. Save to project directory ───────────────────────────────
            point_layer.updateExtents()
            layer_name = "extracted_points"
            project_path = QgsProject.instance().homePath()

            if not project_path:
                print("Warning: Project not saved. Using memory layer.")
                point_layer.setName(layer_name)
                QgsProject.instance().addMapLayer(point_layer)
            else:
                output_path = os.path.join(project_path, f"{layer_name}.gpkg")

                options = QgsVectorFileWriter.SaveVectorOptions()
                options.driverName = "GPKG"
                options.fileEncoding = "UTF-8"

                error = QgsVectorFileWriter.writeAsVectorFormatV3(
                    point_layer,
                    output_path,
                    QgsProject.instance().transformContext(),
                    options,
                )

                if error[0] == QgsVectorFileWriter.NoError:
                    saved_layer = QgsVectorLayer(output_path, layer_name, "ogr")
                    QgsProject.instance().addMapLayer(saved_layer)
                    print(f"Done: {point_id} vertices saved to {output_path}")
                else:
                    print(f"Error saving: {error[1]}")
                    point_layer.setName(layer_name)
                    QgsProject.instance().addMapLayer(point_layer)

            print(f"Done: {point_id} vertices extracted")
