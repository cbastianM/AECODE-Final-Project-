using RobotOM;
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Threading;

namespace GithubConnect
{
    public static class GeometryMapper
    {
        public static JsafProject Extract(IRobotApplication robApp, Action<string> onProgress)
        {
            var str = robApp.Project.Structure;
            var project = new JsafProject
            {
                Name = robApp.Project.Name ?? "Model",
                Description = $"Exported {DateTime.Now:yyyy-MM-dd HH:mm}"
            };

            var sectionMap = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            var materialMap = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            var nodeIndex = new Dictionary<string, int>();

            var tMat = new Thread(() =>
            {
                onProgress?.Invoke("Extracting materials & sections...");
                ExtractMaterialsAndSections(str, project, out sectionMap, out materialMap);
            });
            var tNodes = new Thread(() =>
            {
                onProgress?.Invoke("Extracting nodes...");
                ExtractNodes(str, project, robApp, out nodeIndex);
            });
            tMat.Start(); tNodes.Start();
            tMat.Join(); tNodes.Join();

            var tBars = new Thread(() =>
            {
                onProgress?.Invoke("Extracting bars...");
                ExtractBars(str, project, sectionMap, robApp);
            });
            var tSurf = new Thread(() =>
            {
                onProgress?.Invoke("Extracting surfaces...");
                ExtractSurfaces(str, project, materialMap, nodeIndex);
            });
            tBars.Start(); tSurf.Start();
            tBars.Join(); tSurf.Join();

            onProgress?.Invoke("Done");
            return project;
        }

        private static void ExtractMaterialsAndSections(
            IRobotStructure str, JsafProject project,
            out Dictionary<string, string> sectionMap,
            out Dictionary<string, string> materialMap)
        {
            sectionMap = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            materialMap = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

            var labels = str.Labels;
            if (labels == null) return;

            var matNames = labels.GetAvailableNames(IRobotLabelType.I_LT_MATERIAL);
            if (matNames == null) return;

            for (int i = 1; i <= matNames.Count; i++)
            {
                string name = matNames.Get(i);
                if (string.IsNullOrWhiteSpace(name)) continue;

                var label = labels.Get(IRobotLabelType.I_LT_MATERIAL, name);
                if (label == null || label.Data == null) continue;
                IRobotMaterialData data = (IRobotMaterialData)label.Data;

                string id = Guid.NewGuid().ToString();
                string type = "Other";
                if (data.Type == IRobotMaterialType.I_MT_CONCRETE) type = "Concrete";
                else if (data.Type == IRobotMaterialType.I_MT_STEEL) type = "Steel";

                var mat = new Material
                {
                    Id = id,
                    Name = name,
                    Type = type,
                    EModulus = data.E / 1000.0,
                    PoissonCoefficient = data.NU,
                    UnitMass = data.RO,
                    ThermalExpansion = data.LX,
                    GModulus = data.Kirchoff / 1000.0
                };
                if (type == "Concrete") mat.Fck = data.RE / 1000.0;
                if (type == "Steel") { mat.Fy = data.RE / 1000.0; mat.Fu = data.RT / 1000.0; }

                project.Materials.Add(mat);
                if (!materialMap.ContainsKey(name)) materialMap[name] = id;
            }

            var secNames = labels.GetAvailableNames(IRobotLabelType.I_LT_BAR_SECTION);
            if (secNames == null) return;

            for (int i = 1; i <= secNames.Count; i++)
            {
                string name = secNames.Get(i);
                if (string.IsNullOrWhiteSpace(name)) continue;

                var label = labels.Get(IRobotLabelType.I_LT_BAR_SECTION, name);
                if (label == null || label.Data == null) continue;
                IRobotBarSectionData secData = (IRobotBarSectionData)label.Data;

                string matId = "";
                try
                {
                    string matName = secData.MaterialName ?? "";
                    if (!string.IsNullOrWhiteSpace(matName))
                        materialMap.TryGetValue(matName, out matId);
                }
                catch { }

                var cs = MapCrossSection(name, secData, matId ?? "");
                if (cs != null)
                {
                    project.CrossSections.Add(cs);
                    if (!sectionMap.ContainsKey(name)) sectionMap[name] = cs.Id;
                }
            }
        }

        private static CrossSection MapCrossSection(string name, IRobotBarSectionData secData, string matId)
        {
            var materials = string.IsNullOrEmpty(matId)
                ? new List<string>()
                : new List<string> { matId };

            try
            {
                IRobotBarSectionConcreteData c = secData.Concrete;
                if (c != null)
                {
                    try
                    {
                        double d = c.GetValue(IRobotBarSectionConcreteDataValue.I_BSCDV_COL_DE);
                        if (d > 0) return new CrossSection { Id = Guid.NewGuid().ToString(), Name = name, Shape = "Circle", Parameters = new List<double> { d }, Materials = materials };
                    }
                    catch { }
                    try
                    {
                        double h = c.GetValue(IRobotBarSectionConcreteDataValue.I_BSCDV_COL_H);
                        double b = c.GetValue(IRobotBarSectionConcreteDataValue.I_BSCDV_COL_B);
                        if (h > 0 || b > 0) return new CrossSection { Id = Guid.NewGuid().ToString(), Name = name, Shape = "Rectangle", Parameters = new List<double> { h, b }, Materials = materials };
                    }
                    catch { }
                    try
                    {
                        double h = c.GetValue(IRobotBarSectionConcreteDataValue.I_BSCDV_BEAM_RECT_H);
                        double b = c.GetValue(IRobotBarSectionConcreteDataValue.I_BSCDV_BEAM_RECT_B);
                        if (h > 0 || b > 0) return new CrossSection { Id = Guid.NewGuid().ToString(), Name = name, Shape = "Rectangle", Parameters = new List<double> { h, b }, Materials = materials };
                    }
                    catch { }
                }
            }
            catch { }

            try
            {
                IRobotBarSectionNonstdData ns = secData.CreateNonstd(0);
                if (ns != null)
                {
                    double tw = 0, bf = 0, tf = 0, hw = 0;
                    try { tw = ns.GetValue((IRobotBarSectionNonstdDataValue)3); } catch { }
                    try { bf = ns.GetValue((IRobotBarSectionNonstdDataValue)1); } catch { }
                    try { tf = ns.GetValue((IRobotBarSectionNonstdDataValue)2); } catch { }
                    try { hw = ns.GetValue((IRobotBarSectionNonstdDataValue)0); } catch { }
                    if (tw > 0 || bf > 0 || hw > 0)
                        return new CrossSection { Id = Guid.NewGuid().ToString(), Name = name, Shape = "ISection", Parameters = new List<double> { bf, hw, tw, tf }, Materials = materials };
                }
            }
            catch { }

            return new CrossSection { Id = Guid.NewGuid().ToString(), Name = name, Shape = "General", Parameters = new List<double>(), Materials = materials };
        }

        private static void ExtractNodes(IRobotStructure str, JsafProject project, IRobotApplication robApp, out Dictionary<string, int> nodeIndex)
        {
            nodeIndex = new Dictionary<string, int>();
            var table = robApp.Project.ViewMngr.CreateTable(IRobotTableType.I_TT_NODES, IRobotTableDataType.I_TDT_DEFAULT);
            string tmp = Path.Combine(Path.GetTempPath(), $"nodes_{Guid.NewGuid()}.txt");
            table.Printable.SaveToFile(tmp, IRobotOutputFileFormat.I_OFF_TEXT);
            string[] lines = File.ReadAllLines(tmp);
            File.Delete(tmp);

            for (int i = 1; i < lines.Length; i++)
            {
                var parts = lines[i].Split(';');
                if (parts.Length < 4) continue;
                if (!int.TryParse(parts[0].Trim(), out int id)) continue;
                double x = ParseDouble(parts[1]);
                double y = ParseDouble(parts[2]);
                double z = ParseDouble(parts[3]);
                project.PointConnections.Add(new PointConnection { Id = id.ToString(), Name = $"N{id}", X = x, Y = y, Z = z });
                string key = $"{x:F6}_{y:F6}_{z:F6}";
                if (!nodeIndex.ContainsKey(key)) nodeIndex[key] = id;
            }
        }

        private static void ExtractBars(IRobotStructure str, JsafProject project, Dictionary<string, string> sectionMap, IRobotApplication robApp)
        {
            var table = robApp.Project.ViewMngr.CreateTable(IRobotTableType.I_TT_BARS, IRobotTableDataType.I_TDT_DEFAULT);
            string tmp = Path.Combine(Path.GetTempPath(), $"bars_{Guid.NewGuid()}.txt");
            table.Printable.SaveToFile(tmp, IRobotOutputFileFormat.I_OFF_TEXT);
            string[] lines = File.ReadAllLines(tmp);
            File.Delete(tmp);

            for (int i = 1; i < lines.Length; i++)
            {
                var parts = lines[i].Split(';');
                if (parts.Length < 4) continue;
                if (!int.TryParse(parts[0].Trim(), out int id)) continue;
                string csId = "";
                string secLabel = parts[3].Trim();
                if (!string.IsNullOrEmpty(secLabel)) sectionMap.TryGetValue(secLabel, out csId);
                string type = "General";
                if (parts.Length > 7)
                {
                    string t = parts[7].Trim().ToLower();
                    if (t.Contains("column") || t.Contains("columna")) type = "Column";
                    else if (t.Contains("beam") || t.Contains("viga")) type = "Beam";
                }
                project.CurveMembers.Add(new CurveMember { Id = id.ToString(), Name = $"Bar{id}", Type = type, Nodes = new List<string> { parts[1].Trim(), parts[2].Trim() }, CrossSection = csId ?? "" });
            }
        }

        private static void ExtractSurfaces(IRobotStructure str, JsafProject project, Dictionary<string, string> materialMap, Dictionary<string, int> nodeIndex)
        {
            if (nodeIndex.Count == 0) return;
            var objServer = str.Objects;
            var sel = str.Selections.Create(IRobotObjectType.I_OT_PANEL);
            for (int id = 1; id <= objServer.FreeNumber; id++)
            {
                try { var obj = objServer.Get(id) as IRobotObjObject; if (obj != null && obj.Main != null && obj.Main.Attribs != null) sel.AddOne(id); } catch { }
            }

            for (int i = 1; i <= sel.Count; i++)
            {
                int panelId = sel.Get(i);
                var obj = str.Objects.Get(panelId) as IRobotObjObject;
                if (obj == null) continue;

                var points = new List<(double x, double y, double z)>();
                try
                {
                    dynamic geom = obj.Main.Geometry;
                    for (int s = 1; s <= geom.Segments.Count; s++)
                    {
                        IRobotGeoSegment seg = (IRobotGeoSegment)geom.Segments.Get(s);
                        points.Add((seg.P1.X, seg.P1.Y, seg.P1.Z));
                    }
                }
                catch { continue; }
                if (points.Count < 3) continue;

                var nodeIds = new List<string>();
                foreach (var pt in points)
                {
                    string key = $"{pt.x:F6}_{pt.y:F6}_{pt.z:F6}";
                    if (nodeIndex.TryGetValue(key, out int nid)) nodeIds.Add(nid.ToString());
                }
                if (nodeIds.Count < 3) continue;

                string surfType = "Shell";
                try { dynamic d = obj; int st = (int)d.StructuralType; if (st == 4) surfType = "Plate"; else if (st == 5) surfType = "Wall"; } catch { }

                string matId = "";
                try
                {
                    IRobotLabel thickLabel = obj.GetLabel(IRobotLabelType.I_LT_PANEL_THICKNESS);
                    if (thickLabel != null && thickLabel.Data != null)
                    {
                        IRobotThicknessData td = (IRobotThicknessData)thickLabel.Data;
                        string matName = td.MaterialName ?? "";
                        if (!string.IsNullOrEmpty(matName)) materialMap.TryGetValue(matName, out matId);
                    }
                }
                catch { }

                int thickness = 0;
                try
                {
                    IRobotLabel thickLabel = obj.GetLabel(IRobotLabelType.I_LT_PANEL_THICKNESS);
                    if (thickLabel != null && thickLabel.Data != null)
                    {
                        IRobotThicknessData td = (IRobotThicknessData)thickLabel.Data;
                        if (td.ThicknessType == IRobotThicknessType.I_TT_HOMOGENEOUS)
                        {
                            IRobotThicknessHomoData homo = (IRobotThicknessHomoData)td.Data;
                            thickness = (int)Math.Round(homo.ThickConst * 1000);
                        }
                    }
                }
                catch { }

                project.SurfaceMembers.Add(new SurfaceMember
                {
                    Id = panelId.ToString(),
                    Name = $"Panel{panelId}",
                    Type = surfType,
                    Nodes = nodeIds,
                    Materials = string.IsNullOrEmpty(matId) ? new List<string>() : new List<string> { matId ?? "" },
                    Thickness = thickness
                });
            }
        }

        private static double ParseDouble(string s)
        {
            s = s.Trim().Replace(',', '.');
            return double.TryParse(s, NumberStyles.Any, CultureInfo.InvariantCulture, out double v) ? v : 0;
        }
    }
}