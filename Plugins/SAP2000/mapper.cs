
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Runtime.Versioning;
using JSAF;
using SAP2000v1;

[assembly: SupportedOSPlatform("windows")]

public static class SAP2000JSafMapper
{
    public static JSAFProject ProjectMapper(cSapModel sapModel)
    {
        var sw = Stopwatch.StartNew();

        var project = CreateProject(sapModel);

        // ── GEOMETRÍA ──
        var materialMap = ExtractMaterials(sapModel, project);
        var sectionMap = ExtractCrossSections(sapModel, project, materialMap);
        var nodeMap = ExtractNodes(sapModel, project);
        ExtractSupports(sapModel, project, nodeMap);
        var memberMap = ExtractFrames(sapModel, project, sectionMap, nodeMap);
        var surfaceMap = ExtractAreas(sapModel, project, materialMap, nodeMap);

        sw.Stop();
        project.Description = $"Geometry exported in {sw.ElapsedMilliseconds} ms";

        return project;
    }

    static JSAFProject CreateProject(cSapModel sapModel)
    {
        string fileName = sapModel.GetModelFilename(false);
        string name = System.IO.Path.GetFileNameWithoutExtension(fileName);

        return new JSAFProject
        {
            Name = name,
            Id = Guid.NewGuid().ToString(),
            Description = ""
        };
    }

    // ───────────────────────────────────────
    // MATERIALES
    // ───────────────────────────────────────
    static Dictionary<string, string> ExtractMaterials(cSapModel sapModel, JSAFProject project)
    {
        var materialMap = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        project.Materials = new List<Material>();

        int count = 0;
        string[] names = Array.Empty<string>();
        int ret = sapModel.PropMaterial.GetNameList(ref count, ref names);
        if (ret != 0 || count == 0) return materialMap;

        for (int i = 0; i < count; i++)
        {
            string matName = names[i];

            eMatType matType = eMatType.NoDesign;
            int color = 0;
            string notes = "", guid = "";
            ret = sapModel.PropMaterial.GetMaterial(matName, ref matType, ref color, ref notes, ref guid);
            if (ret != 0) continue;

            double e = 0, u = 0, a = 0, g = 0;
            sapModel.PropMaterial.GetMPIsotropic(matName, ref e, ref u, ref a, ref g);

            double w = 0, mass = 0;
            sapModel.PropMaterial.GetWeightAndMass(matName, ref w, ref mass);

            string jsafId = Guid.NewGuid().ToString();
            materialMap[matName] = jsafId;

            if (matType == eMatType.Concrete)
            {
                double fckTemp = 0;
                bool isLightweight = false;
                double fcsFactor = 0;
                int ssType = 0, ssHysType = 0;
                double strainUnconf = 0, strainUltComp = 0, strainUlt = 0, finalSlope = 0, dilAngle = 0;
                sapModel.PropMaterial.GetOConcrete_1(matName, ref fckTemp,
                    ref isLightweight, ref fcsFactor, ref ssType, ref ssHysType,
                    ref strainUnconf, ref strainUltComp, ref strainUlt, ref finalSlope, ref dilAngle);

                project.Materials.Add(new Concrete
                {
                    Id = jsafId,
                    Name = matName,
                    Fck = fckTemp / 1000.0,
                    EModulus = e / 1000.0,
                    GModulus = g / 1000.0,
                    PoissonCoefficient = u,
                    UnitMass = mass,
                    ThermalExpansion = a
                });
            }
            else if (matType == eMatType.Steel)
            {
                double fyTemp = 0, fuTemp = 0, efyTemp = 0, efuTemp = 0;
                int ssType = 0, ssHysType = 0;
                double strHard = 0, strMax = 0, strRup = 0, finalSlope = 0;
                sapModel.PropMaterial.GetOSteel_1(matName, ref fyTemp, ref fuTemp,
                    ref efyTemp, ref efuTemp, ref ssType, ref ssHysType,
                    ref strHard, ref strMax, ref strRup, ref finalSlope);

                project.Materials.Add(new Steel
                {
                    Id = jsafId,
                    Name = matName,
                    SubType = SteelType.Rolled,
                    Fy = fyTemp / 1000.0,
                    Fu = fuTemp / 1000.0,
                    EModulus = e / 1000.0,
                    GModulus = g / 1000.0,
                    PoissonCoefficient = u,
                    UnitMass = mass,
                    ThermalExpansion = a
                });
            }
            else if (matType == eMatType.Rebar)
            {
                double fyTemp = 0, fuTemp = 0, efyTemp = 0, efuTemp = 0;
                int ssType = 0, ssHysType = 0;
                double strHard = 0, strRup = 0, finalSlope = 0;
                bool useCaltrans = false;
                sapModel.PropMaterial.GetORebar_1(matName, ref fyTemp, ref fuTemp,
                    ref efyTemp, ref efuTemp, ref ssType, ref ssHysType,
                    ref strHard, ref strRup, ref finalSlope, ref useCaltrans);

                double eUniaxial = 0, aUniaxial = 0;
                sapModel.PropMaterial.GetMPUniaxial(matName, ref eUniaxial, ref aUniaxial);

                project.Materials.Add(new Steel
                {
                    Id = jsafId,
                    Name = matName,
                    SubType = SteelType.PassiveReinforcement,
                    Fy = fyTemp / 1000.0,
                    Fu = fuTemp / 1000.0,
                    EModulus = eUniaxial / 1000.0,
                    GModulus = 0,
                    PoissonCoefficient = 0,
                    UnitMass = mass,
                    ThermalExpansion = aUniaxial
                });
            }
            else
            {
                project.Materials.Add(new Steel
                {
                    Id = jsafId,
                    Name = matName,
                    Fy = 0,
                    Fu = 0,
                    EModulus = e / 1000.0,
                    GModulus = g / 1000.0,
                    PoissonCoefficient = u,
                    UnitMass = mass,
                    ThermalExpansion = a
                });
            }
        }

        return materialMap;
    }

    // ───────────────────────────────────────
    // SECCIONES TRANSVERSALES
    // ───────────────────────────────────────
    static Dictionary<string, string> ExtractCrossSections(cSapModel sapModel, JSAFProject project,
        Dictionary<string, string> materialMap)
    {
        var sectionMap = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        project.CrossSections = new List<CrossSection>();

        int count = 0;
        string[] names = Array.Empty<string>();
        int ret = sapModel.PropFrame.GetNameList(ref count, ref names);
        if (ret != 0 || count == 0) return sectionMap;

        for (int i = 0; i < count; i++)
        {
            string secName = names[i];
            var cs = DetectCrossSection(sapModel, secName, materialMap);
            if (cs != null)
            {
                sectionMap[secName] = cs.Id;
                project.CrossSections.Add(cs);
            }
        }

        return sectionMap;
    }

    static ParametricCrossSection DetectCrossSection(cSapModel sapModel, string secName,
        Dictionary<string, string> materialMap)
    {
        string fileName = "", matProp = "", notes = "", sGuid = "";
        int color = 0;
        double t3 = 0, t2 = 0, tf = 0, tw = 0, t2b = 0, tfb = 0;

        CrossSectionShape shape = (CrossSectionShape)3;
        var parameters = new List<double>();

        // Rectangle
        int ret = sapModel.PropFrame.GetRectangle(secName, ref fileName, ref matProp,
            ref t3, ref t2, ref color, ref notes, ref sGuid);
        if (ret == 0 && t3 > 0 && t2 > 0)
        {
            shape = (CrossSectionShape)1;
            parameters.Add(t3);
            parameters.Add(t2);
        }
        else
        {
            fileName = ""; matProp = ""; t3 = 0; t2 = 0; tf = 0; tw = 0; t2b = 0; tfb = 0;
            ret = sapModel.PropFrame.GetISection(secName, ref fileName, ref matProp,
                ref t3, ref t2, ref tf, ref tw, ref t2b, ref tfb,
                ref color, ref notes, ref sGuid);
            if (ret == 0 && t3 > 0)
            {
                shape = (CrossSectionShape)6;
                parameters.Add(t2);
                parameters.Add(t3);
                parameters.Add(tw);
                parameters.Add(tf);
            }
            else
            {
                fileName = ""; matProp = "";
                double dia = 0;
                ret = sapModel.PropFrame.GetCircle(secName, ref fileName, ref matProp,
                    ref dia, ref color, ref notes, ref sGuid);
                if (ret == 0 && dia > 0)
                {
                    shape = (CrossSectionShape)0;
                    parameters.Add(dia);
                }
                else
                {
                    fileName = ""; matProp = ""; t3 = 0; t2 = 0;
                    ret = sapModel.PropFrame.GetPipe(secName, ref fileName, ref matProp,
                        ref t3, ref t2, ref color, ref notes, ref sGuid);
                    if (ret == 0 && t3 > 0)
                    {
                        shape = (CrossSectionShape)16;
                        parameters.Add(t3);
                        parameters.Add(t2);
                    }
                    else
                    {
                        fileName = ""; matProp = ""; t3 = 0; t2 = 0; tf = 0; tw = 0;
                        ret = sapModel.PropFrame.GetTee(secName, ref fileName, ref matProp,
                            ref t3, ref t2, ref tf, ref tw,
                            ref color, ref notes, ref sGuid);
                        if (ret == 0 && t3 > 0)
                        {
                            shape = (CrossSectionShape)9;
                            parameters.Add(t3);
                            parameters.Add(t2);
                            parameters.Add(tw);
                            parameters.Add(tf);
                        }
                        else
                        {
                            fileName = ""; matProp = ""; t3 = 0; t2 = 0; tf = 0; tw = 0;
                            ret = sapModel.PropFrame.GetChannel(secName, ref fileName, ref matProp,
                                ref t3, ref t2, ref tf, ref tw,
                                ref color, ref notes, ref sGuid);
                            if (ret == 0 && t3 > 0)
                            {
                                shape = (CrossSectionShape)14;
                                parameters.Add(t3);
                                parameters.Add(t2);
                                parameters.Add(tw);
                                parameters.Add(tf);
                            }
                            else
                            {
                                shape = (CrossSectionShape)3;
                                fileName = ""; matProp = "";
                                double area = 0, as2 = 0, as3 = 0, torsion = 0, i22 = 0, i33 = 0;
                                double s22 = 0, s33 = 0, z22 = 0, z33 = 0, r22 = 0, r33 = 0;
                                t3 = 0; t2 = 0;
                                sapModel.PropFrame.GetGeneral(secName, ref fileName, ref matProp,
                                    ref t3, ref t2, ref area, ref as2, ref as3, ref torsion,
                                    ref i22, ref i33, ref s22, ref s33, ref z22, ref z33,
                                    ref r22, ref r33, ref color, ref notes, ref sGuid);
                            }
                        }
                    }
                }
            }
        }

        string materialId = "";
        if (!string.IsNullOrEmpty(matProp) && materialMap.ContainsKey(matProp))
            materialId = materialMap[matProp];

        return new ParametricCrossSection
        {
            Id = Guid.NewGuid().ToString(),
            Name = secName,
            Shape = shape,
            Parameters = parameters,
            Materials = !string.IsNullOrEmpty(materialId)
                ? new List<string> { materialId }
                : new List<string>()
        };
    }

    // ───────────────────────────────────────
    // NODOS
    // ───────────────────────────────────────
    static Dictionary<string, string> ExtractNodes(cSapModel sapModel, JSAFProject project)
    {
        var nodeMap = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        project.PointConnections = new List<PointConnection>();

        int count = 0;
        string[] names = Array.Empty<string>();
        int ret = sapModel.PointObj.GetNameList(ref count, ref names);
        if (ret != 0 || count == 0) return nodeMap;

        var nodes = new List<PointConnection>(count);
        for (int i = 0; i < count; i++)
        {
            string nodeName = names[i];
            double x = 0, y = 0, z = 0;
            ret = sapModel.PointObj.GetCoordCartesian(nodeName, ref x, ref y, ref z);
            if (ret != 0) continue;

            nodeMap[nodeName] = nodeName;

            nodes.Add(new PointConnection
            {
                Id = nodeName,
                Name = $"N{nodeName}",
                X = x,
                Y = y,
                Z = z
            });
        }

        project.PointConnections = nodes;
        return nodeMap;
    }

    // ───────────────────────────────────────
    // APOYOS
    // ───────────────────────────────────────
    static void ExtractSupports(cSapModel sapModel, JSAFProject project,
        Dictionary<string, string> nodeMap)
    {
        project.PointSupports = new List<PointSupport>();

        int count = 0;
        string[] names = Array.Empty<string>();
        int ret = sapModel.PointObj.GetNameList(ref count, ref names);
        if (ret != 0 || count == 0) return;

        for (int i = 0; i < count; i++)
        {
            string nodeName = names[i];

            bool[] restraints = new bool[6];
            ret = sapModel.PointObj.GetRestraint(nodeName, ref restraints);
            if (ret != 0) continue;

            bool hasRestraint = false;
            for (int j = 0; j < 6; j++)
            {
                if (restraints[j]) { hasRestraint = true; break; }
            }
            if (!hasRestraint) continue;

            double[] springs = new double[6];
            sapModel.PointObj.GetSpring(nodeName, ref springs);

            string nodeId = nodeMap.ContainsKey(nodeName) ? nodeMap[nodeName] : nodeName;

            project.PointSupports.Add(new NodalSupport
            {
                Id = Guid.NewGuid().ToString(),
                Name = $"Sup{nodeName}",
                Node = nodeId,
                Ux = MapTranslation(restraints[0], springs[0]),
                Uy = MapTranslation(restraints[1], springs[1]),
                Uz = MapTranslation(restraints[2], springs[2]),
                Fix = MapRotation(restraints[3], springs[3]),
                Fiy = MapRotation(restraints[4], springs[4]),
                Fiz = MapRotation(restraints[5], springs[5])
            });
        }
    }

    static PointTranslationRestrictions MapTranslation(bool restrained, double spring)
    {
        if (restrained) return PointTranslationRestrictions.Rigid;
        if (spring > 0) return PointTranslationRestrictions.Flexible;
        return PointTranslationRestrictions.Free;
    }

    static PointRotationRestrictions MapRotation(bool restrained, double spring)
    {
        if (restrained) return PointRotationRestrictions.Rigid;
        if (spring > 0) return PointRotationRestrictions.Flexible;
        return PointRotationRestrictions.Free;
    }

    // ───────────────────────────────────────
    // FRAMES → CurveMembers
    // ───────────────────────────────────────
    static Dictionary<string, string> ExtractFrames(cSapModel sapModel, JSAFProject project,
        Dictionary<string, string> sectionMap, Dictionary<string, string> nodeMap)
    {
        var memberMap = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        project.CurveMembers = new List<CurveMember>();

        int count = 0;
        string[] names = Array.Empty<string>();
        int ret = sapModel.FrameObj.GetNameList(ref count, ref names);
        if (ret != 0 || count == 0) return memberMap;

        for (int i = 0; i < count; i++)
        {
            string frameName = names[i];

            string point1 = "", point2 = "";
            ret = sapModel.FrameObj.GetPoints(frameName, ref point1, ref point2);
            if (ret != 0) continue;

            string secProp = "";
            string sAuto = "";
            sapModel.FrameObj.GetSection(frameName, ref secProp, ref sAuto);

            string sectionId = "";
            if (!string.IsNullOrEmpty(secProp) && sectionMap.ContainsKey(secProp))
                sectionId = sectionMap[secProp];

            string nodeI = nodeMap.ContainsKey(point1) ? nodeMap[point1] : point1;
            string nodeJ = nodeMap.ContainsKey(point2) ? nodeMap[point2] : point2;

            CurveMemberType memberType = DetectMemberType(sapModel, frameName, nodeMap);

            string memberId = frameName;
            memberMap[frameName] = memberId;

            project.CurveMembers.Add(new CurveMember
            {
                Id = memberId,
                Name = $"Bar{frameName}",
                Type = memberType,
                Nodes = new List<string> { nodeI, nodeJ },
                CrossSection = sectionId
            });
        }

        return memberMap;
    }

    static CurveMemberType DetectMemberType(cSapModel sapModel, string frameName,
        Dictionary<string, string> nodeMap)
    {
        string point1 = "", point2 = "";
        int ret = sapModel.FrameObj.GetPoints(frameName, ref point1, ref point2);
        if (ret != 0) return CurveMemberType.General;

        double x1 = 0, y1 = 0, z1 = 0;
        double x2 = 0, y2 = 0, z2 = 0;
        sapModel.PointObj.GetCoordCartesian(point1, ref x1, ref y1, ref z1);
        sapModel.PointObj.GetCoordCartesian(point2, ref x2, ref y2, ref z2);

        double dx = Math.Abs(x2 - x1);
        double dy = Math.Abs(y2 - y1);
        double dz = Math.Abs(z2 - z1);
        double length = Math.Sqrt(dx * dx + dy * dy + dz * dz);
        if (length < 1e-9) return CurveMemberType.General;

        double verticalRatio = dz / length;
        if (verticalRatio > 0.7) return CurveMemberType.Column;
        return CurveMemberType.Beam;
    }

    // ───────────────────────────────────────
    // AREAS → SurfaceMembers + SurfaceMemberRegions
    // ───────────────────────────────────────
    static Dictionary<string, string> ExtractAreas(cSapModel sapModel, JSAFProject project,
        Dictionary<string, string> materialMap, Dictionary<string, string> nodeMap)
    {
        var surfaceMap = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        project.SurfaceMembers = new List<SurfaceMember>();
        project.SurfaceMemberRegions = new List<SurfaceMemberRegion>();

        int count = 0;
        string[] names = Array.Empty<string>();
        int ret = sapModel.AreaObj.GetNameList(ref count, ref names);
        if (ret != 0 || count == 0) return surfaceMap;

        for (int i = 0; i < count; i++)
        {
            string areaName = names[i];

            int numPoints = 0;
            string[] pointNames = Array.Empty<string>();
            ret = sapModel.AreaObj.GetPoints(areaName, ref numPoints, ref pointNames);
            if (ret != 0 || numPoints < 3) continue;

            var nodeIds = new List<string>(numPoints);
            var coords = new List<(double x, double y, double z)>(numPoints);
            for (int j = 0; j < numPoints; j++)
            {
                string ptName = pointNames[j];
                string nId = nodeMap.ContainsKey(ptName) ? nodeMap[ptName] : ptName;
                nodeIds.Add(nId);

                double px = 0, py = 0, pz = 0;
                sapModel.PointObj.GetCoordCartesian(ptName, ref px, ref py, ref pz);
                coords.Add((px, py, pz));
            }

            // Obtener propiedad de área
            string secProp = "";
            sapModel.AreaObj.GetProperty(areaName, ref secProp);

            int thicknessMm = 0;
            string matId = "";

            if (!string.IsNullOrEmpty(secProp))
            {
                int shellType = 0;
                bool includeDrillingDOF = false;
                string shellMatProp = "";
                double matAngle = 0;
                double memThick = 0, bendThick = 0;
                int sColor = 0;
                string sNotes = "", sGuid = "";

                ret = sapModel.PropArea.GetShell_1(secProp, ref shellType,
                    ref includeDrillingDOF, ref shellMatProp, ref matAngle,
                    ref memThick, ref bendThick, ref sColor, ref sNotes, ref sGuid);
                if (ret == 0)
                {
                    double thick = memThick > 0 ? memThick : bendThick;
                    thicknessMm = (int)(thick * 1000);
                    if (!string.IsNullOrEmpty(shellMatProp) && materialMap.ContainsKey(shellMatProp))
                        matId = materialMap[shellMatProp];
                }
            }

            // Detectar tipo por normal
            SurfaceMemberType surfaceType = DetectSurfaceType(coords);

            // Calcular LCS
            var (lcsX, lcsY, lcsZ) = ComputeLCS(coords, surfaceType);

            string surfaceId = areaName;
            surfaceMap[areaName] = surfaceId;

            var edges = new List<SegmentType>(numPoints);
            for (int j = 0; j < numPoints; j++)
                edges.Add(SegmentType.Line);

            project.SurfaceMembers.Add(new SurfaceMember
            {
                Id = surfaceId,
                Name = $"Panel{areaName}",
                Type = surfaceType,
                Nodes = nodeIds,
                Materials = !string.IsNullOrEmpty(matId)
                    ? new List<string> { matId }
                    : new List<string>(),
                Thickness = thicknessMm,
                InternalNodes = new List<string>(),
                Edges = edges,
                LCS = LCSSurface.XByVector,
                LCSRotation = 0,
                LCSX = lcsX,
                LCSY = lcsY,
                LCSZ = lcsZ
            });

            // Region
            var closedNodes = new List<string>(nodeIds);
            if (closedNodes.Count > 0 && closedNodes[0] != closedNodes[closedNodes.Count - 1])
                closedNodes.Add(closedNodes[0]);

            var regionEdges = new List<SegmentType>(closedNodes.Count);
            for (int j = 0; j < closedNodes.Count; j++)
                regionEdges.Add(SegmentType.Line);

            project.SurfaceMemberRegions.Add(new SurfaceMemberRegion
            {
                Id = $"{surfaceId}_region0",
                Name = $"Panel{areaName}_region0",
                Surface = surfaceId,
                Nodes = closedNodes,
                Thickness = thicknessMm,
                SystemPlane = 0,
                Eccentricity = 0,
                Area = 0.0,
                Edges = regionEdges
            });
        }

        return surfaceMap;
    }

    static SurfaceMemberType DetectSurfaceType(List<(double x, double y, double z)> coords)
    {
        if (coords.Count < 3) return SurfaceMemberType.Shell;

        var p0 = coords[0];
        var p1 = coords[1];
        var p2 = coords[2];

        double v1x = p1.x - p0.x, v1y = p1.y - p0.y, v1z = p1.z - p0.z;
        double v2x = p2.x - p0.x, v2y = p2.y - p0.y, v2z = p2.z - p0.z;

        double nx = v1y * v2z - v1z * v2y;
        double ny = v1z * v2x - v1x * v2z;
        double nz = v1x * v2y - v1y * v2x;
        double len = Math.Sqrt(nx * nx + ny * ny + nz * nz);

        if (len < 1e-9) return SurfaceMemberType.Shell;

        double nzAbs = Math.Abs(nz / len);
        return nzAbs > 0.7 ? SurfaceMemberType.Plate : SurfaceMemberType.Wall;
    }

    static (double lcsX, double lcsY, double lcsZ) ComputeLCS(
        List<(double x, double y, double z)> coords, SurfaceMemberType surfaceType)
    {
        if (coords.Count < 2) return (1, 0, 0);

        double dx = coords[1].x - coords[0].x;
        double dy = coords[1].y - coords[0].y;
        double dz = coords[1].z - coords[0].z;

        if (surfaceType == SurfaceMemberType.Plate)
            dz = 0;

        double len = Math.Sqrt(dx * dx + dy * dy + dz * dz);
        if (len < 1e-9) return (1, 0, 0);

        return (dx / len, dy / len, dz / len);
    }
}
