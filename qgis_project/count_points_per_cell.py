import os
import csv
from collections import defaultdict
from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsField,
    QgsWkbTypes,
)
from qgis.PyQt.QtWidgets import QInputDialog
from qgis.PyQt.QtCore import QVariant

# ── Get layers by geometry type ──────────────────────────────────────────
polygon_layers = [
    layer.name()
    for layer in QgsProject.instance().mapLayers().values()
    if isinstance(layer, QgsVectorLayer)
    and layer.geometryType() == QgsWkbTypes.PolygonGeometry
]

point_layers = [
    layer.name()
    for layer in QgsProject.instance().mapLayers().values()
    if isinstance(layer, QgsVectorLayer)
    and layer.geometryType() == QgsWkbTypes.PointGeometry
]

if not polygon_layers:
    print("No polygon layers found")
elif not point_layers:
    print("No point layers found")
else:
    # Select grid layer (polygons)
    grid_name, ok1 = QInputDialog.getItem(
        None,
        "Grid layer",
        "Select the UTM grid layer:",
        polygon_layers,
        0,
        False,
    )

    if not ok1:
        print("Cancelled")
    else:
        # Select points layer
        points_name, ok2 = QInputDialog.getItem(
            None,
            "Points layer",
            "Select the points layer:",
            point_layers,
            0,
            False,
        )

        if not ok2:
            print("Cancelled")
        else:
            grid_layer = QgsProject.instance().mapLayersByName(grid_name)[0]
            points_layer = QgsProject.instance().mapLayersByName(points_name)[0]

            # ── 1. Get cell size from first grid cell ────────────────────
            first_cell = next(grid_layer.getFeatures())
            bbox = first_cell.geometry().boundingBox()
            step = int(round(bbox.width()))
            print(f"Detected cell size: {step} m")

            # ── 2. Count points per cell using coordinates ──────────────
            print("Counting points per cell...")
            cell_counts = defaultdict(int)

            for pt_feat in points_layer.getFeatures():
                pt = pt_feat.geometry().asPoint()
                cell_x = int(pt.x() // step) * step
                cell_y = int(pt.y() // step) * step
                cell_counts[(cell_x, cell_y)] += 1

            print(f"Counted points in {len(cell_counts)} cells")

            # ── 3. Add points field if not exists ────────────────────────
            field_name = "points"
            if grid_layer.fields().indexOf(field_name) == -1:
                grid_layer.dataProvider().addAttributes(
                    [QgsField(field_name, QVariant.Int)]
                )
                grid_layer.updateFields()

            idx_points = grid_layer.fields().indexOf(field_name)
            idx_mgrs = grid_layer.fields().indexOf("mgrs")

            # ── 4. Update grid layer and collect results ─────────────────
            results = []

            grid_layer.startEditing()
            for cell_feat in grid_layer.getFeatures():
                bbox = cell_feat.geometry().boundingBox()
                cell_x = int(bbox.xMinimum() // step) * step
                cell_y = int(bbox.yMinimum() // step) * step

                point_count = cell_counts.get((cell_x, cell_y), 0)
                mgrs = cell_feat["mgrs"] if idx_mgrs >= 0 else str(cell_feat.id())

                grid_layer.changeAttributeValue(cell_feat.id(), idx_points, point_count)
                results.append({"mgrs": mgrs, "points": point_count})

            grid_layer.commitChanges()

            # ── 5. Save CSV to project directory ─────────────────────────
            project_path = QgsProject.instance().homePath()

            if not project_path:
                print("Warning: Project not saved. CSV not created.")
            else:
                csv_path = os.path.join(project_path, f"points_per_cell_{step}.csv")

                with open(csv_path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=["mgrs", "points"])
                    writer.writeheader()
                    writer.writerows(results)

                print(f"CSV saved to {csv_path}")

            total_points = sum(r["points"] for r in results)
            print(f"Done: {total_points} points in {len(results)} cells")
