import os
from qgis.core import (
    QgsProject,
    QgsField,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsVectorLayer,
    QgsVectorFileWriter,
    QgsSymbol,
    QgsPalLayerSettings,
    QgsVectorLayerSimpleLabeling,
    QgsTextFormat,
)
from qgis.PyQt.QtWidgets import QInputDialog
from qgis.PyQt.QtCore import QVariant
from PyQt5.QtGui import QColor, QFont

# ── 0. Layer selection ───────────────────────────────────────────────
available_layers = [
    layer.name() for layer in QgsProject.instance().mapLayers().values()
]
if not available_layers:
    print("No layers in the project")
else:
    # ── 1. Points layer selection ────────────────────────────────────
    points_name, ok_points = QInputDialog.getItem(
        None,
        "Points layer",
        "Select the points layer (extracted_points):",
        available_layers,
        0,
        False,
    )

    if not ok_points:
        print("Cancelled")
    else:
        # ── 2. Resolution selection ──────────────────────────────────
        options = ["10 km", "1 km"]
        option, ok = QInputDialog.getItem(
            None, "Grid resolution", "Select the cell size:", options, 0, False
        )

        if not ok:
            print("Cancelled")
        else:
            step = 10000 if option == "10 km" else 1000
            points_layer = QgsProject.instance().mapLayersByName(points_name)[0]

            # ── 3. Find unique cells from point coordinates ──────────
            print("Calculating cells from point coordinates...")
            cells = set()
            for feat in points_layer.getFeatures():
                pt = feat.geometry().asPoint()
                # Calculate cell origin (lower left corner)
                cell_x = int(pt.x() // step) * step
                cell_y = int(pt.y() // step) * step
                cells.add((cell_x, cell_y))

            print(f"Found {len(cells)} unique cells")

            # ── 4. Create grid layer with only needed cells ──────────
            crs = points_layer.crs().authid()
            grid_layer = QgsVectorLayer(f"Polygon?crs={crs}", "temp_grid", "memory")
            provider = grid_layer.dataProvider()
            provider.addAttributes([QgsField("mgrs", QVariant.String)])
            grid_layer.updateFields()

            # ── 5. MGRS calculation functions ────────────────────────
            NORTH_LETTERS_ODD = [
                "A", "B", "C", "D", "E", "F", "G", "H", "J", "K",
                "L", "M", "N", "P", "Q", "R", "S", "T", "U", "V",
            ]

            def mgrs_100km(easting, northing, utm_zone=31):
                col = int(easting // 100000)
                letters_e = (
                    ["A", "B", "C", "D", "E", "F", "G", "H"]
                    if utm_zone % 2 == 1
                    else ["J", "K", "L", "M", "N", "P", "Q", "R"]
                )
                letter_e = letters_e[col - 1]
                row = int(northing // 100000) % 20
                offset = 0 if utm_zone % 2 == 1 else 5
                letter_n = NORTH_LETTERS_ODD[(row + offset) % 20]
                return letter_e + letter_n

            def latitude_band(northing):
                bands = [
                    "C", "D", "E", "F", "G", "H", "J", "K", "L", "M",
                    "N", "P", "Q", "R", "S", "T", "U", "V", "W", "X",
                ]
                idx = int((northing / 110540 - (-80)) / 8)
                return bands[max(0, min(idx, len(bands) - 1))]

            step_km = 10 if option == "10 km" else 1
            digits = 1 if option == "10 km" else 2
            fmt = f"{{:0{digits}d}}"

            # ── 6. Create cell features ──────────────────────────────
            features = []
            for cell_x, cell_y in cells:
                # Create rectangle polygon
                rect = QgsGeometry.fromPolygonXY([[
                    QgsPointXY(cell_x, cell_y),
                    QgsPointXY(cell_x + step, cell_y),
                    QgsPointXY(cell_x + step, cell_y + step),
                    QgsPointXY(cell_x, cell_y + step),
                    QgsPointXY(cell_x, cell_y),
                ]])

                # Calculate MGRS label
                band = latitude_band(cell_y)
                letters = mgrs_100km(cell_x, cell_y)
                e_local = int((cell_x % 100000) // (step_km * 1000))
                n_local = int((cell_y % 100000) // (step_km * 1000))
                label = f"31{band}{letters}{fmt.format(e_local)}{fmt.format(n_local)}"

                feat = QgsFeature(grid_layer.fields())
                feat.setGeometry(rect)
                feat.setAttribute("mgrs", label)
                features.append(feat)

            provider.addFeatures(features)
            grid_layer.updateExtents()

            # ── 7. Style: no fill ────────────────────────────────────
            symbol = QgsSymbol.defaultSymbol(grid_layer.geometryType())
            fl = symbol.symbolLayer(0)
            fl.setBrushStyle(0)
            fl.setStrokeColor(QColor(175, 175, 175))
            fl.setStrokeWidth(0.2)
            grid_layer.renderer().setSymbol(symbol)

            # ── 8. Labels ────────────────────────────────────────────
            text_format = QgsTextFormat()
            text_format.setFont(QFont("Arial", 9))
            text_format.setSize(9)
            text_format.setColor(QColor(0, 0, 0))
            label_settings = QgsPalLayerSettings()
            label_settings.fieldName = "mgrs"
            label_settings.enabled = True
            label_settings.setFormat(text_format)
            grid_layer.setLabeling(QgsVectorLayerSimpleLabeling(label_settings))
            grid_layer.setLabelsEnabled(True)

            # ── 9. Save to project directory ────────────────────────
            grid_name = f"utm_grid_{option.replace(' ', '')}"
            project_path = QgsProject.instance().homePath()

            if not project_path:
                print("Warning: Project not saved. Using memory layer.")
                grid_layer.setName(grid_name)
                QgsProject.instance().addMapLayer(grid_layer)
            else:
                output_path = os.path.join(project_path, f"{grid_name}.gpkg")

                options = QgsVectorFileWriter.SaveVectorOptions()
                options.driverName = "GPKG"
                options.fileEncoding = "UTF-8"

                error = QgsVectorFileWriter.writeAsVectorFormatV3(
                    grid_layer,
                    output_path,
                    QgsProject.instance().transformContext(),
                    options,
                )

                if error[0] == QgsVectorFileWriter.NoError:
                    # Load saved layer
                    saved_layer = QgsVectorLayer(output_path, grid_name, "ogr")

                    # Apply style
                    symbol = QgsSymbol.defaultSymbol(saved_layer.geometryType())
                    fl = symbol.symbolLayer(0)
                    fl.setBrushStyle(0)
                    fl.setStrokeColor(QColor(175, 175, 175))
                    fl.setStrokeWidth(0.2)
                    saved_layer.renderer().setSymbol(symbol)

                    # Apply labels
                    saved_layer.setLabeling(QgsVectorLayerSimpleLabeling(label_settings))
                    saved_layer.setLabelsEnabled(True)

                    QgsProject.instance().addMapLayer(saved_layer)
                    print(f"Done: {len(cells)} cells saved to {output_path}")
                else:
                    print(f"Error saving: {error[1]}")
                    grid_layer.setName(grid_name)
                    QgsProject.instance().addMapLayer(grid_layer)
