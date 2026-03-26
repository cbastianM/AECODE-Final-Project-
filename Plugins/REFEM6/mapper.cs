
using Dlubal.Api.Common;
using Google.Protobuf;
using Common = Dlubal.Api.Common;
using Rfem = Dlubal.Api.Rfem;
using JSAF;
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Threading.Tasks;

public static class RfemMapper
{
    public static ApplicationRfem? app;
    public static Dictionary<int, string> MaterialMap { get; private set; } = new Dictionary<int, string>();
    public static Dictionary<int, string> SectionMap { get; private set; } = new Dictionary<int, string>();

    public static Dictionary<int, string> NodeMap { get; private set; } = new Dictionary<int, string>();

    public static Dictionary<int, string> MemberMap { get; private set; } = new Dictionary<int, string>();

    public static async Task<bool> Connect(string apiKey)
    {
        try
        {
            app = new ApplicationRfem(apiKeyValue: apiKey);
            var info = await app.get_application_info();
            return true;
        }
        catch
        {
            return false;
        }
    }

    public static async Task CloseConnection()
    {
        if (app != null) await app.close_connection();
    }

    // -----------------------------------------------
    // MATERIALES (solo concreto)
    // -----------------------------------------------
    public static async Task ReadMaterials(JSAFProject project)
    {
        if (app == null || project == null) return;

        project.Materials = project.Materials ?? new List<Material>();
        MaterialMap = new Dictionary<int, string>();

        var materialIds = await app.get_object_id_list(
            objectType: Rfem.ObjectType.Material
        );

        if (materialIds == null || materialIds.ObjectId.Count == 0) return;

        var materialNumbers = materialIds.ObjectId.Select(o => o.No).ToList();

        foreach (int matNo in materialNumbers)
        {
            try
            {
                var mat = await app.get_object<Rfem.StructureCore.Material>(
                    new Rfem.StructureCore.Material { No = matNo }
                );

                if (mat == null || string.IsNullOrEmpty(mat.Name)) continue;

                string materialType = mat.MaterialType.ToString().ToLower();

                double e = GetMaterialTreeValue(mat, "e") / 1_000_000.0;
                double nu = GetMaterialTreeValue(mat, "nu");
                double g = GetMaterialTreeValue(mat, "g") / 1_000_000.0;
                double rho = GetMaterialTreeValue(mat, "rho");
                double alpha = GetMaterialTreeValue(mat, "alpha");

                string id = Guid.NewGuid().ToString();

                if (materialType.Contains("concrete"))
                {
                    double fck = GetMaterialTreeValue(mat, "f_ck") / 1_000_000.0;
                    double fcm = GetMaterialTreeValue(mat, "f_cm") / 1_000_000.0;
                    double fctm = GetMaterialTreeValue(mat, "f_ctm") / 1_000_000.0;

                    project.Materials.Add(new Concrete
                    {
                        Id = id,
                        Name = mat.Name,
                        UnitMass = rho,
                        EModulus = e,
                        GModulus = g,
                        PoissonCoefficient = nu,
                        ThermalExpansion = alpha,
                        Fck = fck,
                        Fcm = fcm,
                        Fctm = fctm
                    });
                }
                else if (materialType.Contains("steel"))
                {
                    double fy = GetMaterialTreeValue(mat, "f_y") / 1_000_000.0;
                    double fu = GetMaterialTreeValue(mat, "f_u") / 1_000_000.0;

                    project.Materials.Add(new Steel
                    {
                        Id = id,
                        Name = mat.Name,
                        UnitMass = rho,
                        EModulus = e,
                        GModulus = g,
                        PoissonCoefficient = nu,
                        ThermalExpansion = alpha,
                        Fy = fy,
                        Fu = fu
                    });
                }
                else
                {
                    continue;
                }

                MaterialMap[matNo] = id;
            }
            catch { continue; }
        }
    }

    private static double GetMaterialTreeValue(Rfem.StructureCore.Material mat, string key)
    {
        try
        {
            if (mat.MaterialValues == null || mat.MaterialValues.Rows.Count == 0)
                return 0;

            var tree = mat.MaterialValues.Rows[0].MaterialValuesTree;

            var values = Common.TreeTable.GetValuesByKey(
                tree: tree,
                key: key
            );

            if (values != null && values.Count > 0)
            {
                if (values[0] is double d) return d;
                if (double.TryParse(
                    values[0].ToString()?.Replace(',', '.') ?? "0",
                    NumberStyles.Any,
                    CultureInfo.InvariantCulture,
                    out double parsed))
                    return parsed;
            }
        }
        catch { }
        return 0;
    }

    // -----------------------------------------------
    // SECCIONES
    // -----------------------------------------------
    public static async Task ReadCrossSections(JSAFProject project)
    {
        if (app == null || project == null) return;

        project.CrossSections = project.CrossSections ?? new List<CrossSection>();
        SectionMap = new Dictionary<int, string>();

        var sectionIds = await app.get_object_id_list(
            objectType: Rfem.ObjectType.CrossSection
        );

        if (sectionIds == null || sectionIds.ObjectId.Count == 0) return;

        var sectionNumbers = sectionIds.ObjectId.Select(o => o.No).ToList();

        foreach (int secNo in sectionNumbers)
        {
            try
            {
                var cs = await app.get_object<Rfem.StructureCore.CrossSection>(
                    new Rfem.StructureCore.CrossSection { No = secNo }
                );

                if (cs == null || string.IsNullOrEmpty(cs.Name)) continue;

                // Obtener material vinculado
                int materialNo = cs.Material;
                string? materialId = null;
                if (MaterialMap.TryGetValue(materialNo, out string? matId))
                    materialId = matId;

                // Detectar forma desde ParametrizationType
                string paramType = cs.ParametrizationType.ToString().ToLower();
                ParametricCrossSection? section = MapSection(cs, paramType, materialId);

                if (section != null)
                {
                    project.CrossSections.Add(section);
                    SectionMap[secNo] = section.Id;
                }
            }
            catch { continue; }
        }
    }

    private static ParametricCrossSection? MapSection(
        Rfem.StructureCore.CrossSection cs,
        string paramType,
        string? materialId)
    {
        string id = Guid.NewGuid().ToString();
        var materials = !string.IsNullOrWhiteSpace(materialId)
            ? new List<string> { materialId }
            : new List<string>();

        // Extraer propiedades mecánicas de la API
        double a = 0, iy = 0, iz = 0, it = 0, iw = 0, wply = 0, wplz = 0;
        try { a = cs.A; } catch { }
        try { iy = cs.IY; } catch { }
        try { iz = cs.IZ; } catch { }
        try { it = cs.IT; } catch { }
        try { iw = cs.IOmegaSC; } catch { }
        try { wply = cs.WPlY; } catch { }
        try { wplz = cs.WPlZ; } catch { }

        CrossSectionShape shape;
        List<double> parameters;

        // Rectangle (concreto macizo)
        if (paramType.Contains("massive_rectangle") || paramType.Contains("r_m1"))
        {
            shape = (CrossSectionShape)1; // Rectangle
            parameters = new List<double> { cs.H, cs.B };
        }
        // Circle (concreto macizo)
        else if (paramType.Contains("massive_circle") || paramType.Contains("circle_m1"))
        {
            shape = (CrossSectionShape)0; // Circle
            parameters = new List<double> { cs.D };
        }
        // T Section
        else if (paramType.Contains("massive_t_section") || paramType.Contains("t_m1"))
        {
            shape = (CrossSectionShape)9; // T Section
            parameters = new List<double> { cs.H, cs.B };
        }
        // I Section
        else if (paramType.Contains("massive_i_section") || paramType.Contains("i_m1")
            || paramType.Contains("massive_doubly_symmetric"))
        {
            shape = (CrossSectionShape)6; // I Section
            parameters = new List<double> { cs.H, cs.B };
        }
        // U Section
        else if (paramType.Contains("massive_u_section") || paramType.Contains("u_m1"))
        {
            shape = (CrossSectionShape)14; // U Section
            parameters = new List<double> { cs.H, cs.B };
        }
        // Hollow Circle / Pipe
        else if (paramType.Contains("massive_hollow_circle") || paramType.Contains("hcircle_m1"))
        {
            shape = (CrossSectionShape)16; // Pipe
            parameters = new List<double> { cs.D };
        }
        // Fallback: Rectangle por defecto
        else
        {
            shape = (CrossSectionShape)1;
            parameters = new List<double> { cs.H, cs.B };
        }

        return new ParametricCrossSection
        {
            Id = id,
            Name = cs.Name,
            Shape = shape,
            Parameters = parameters,
            Materials = materials,
            A = a,
            Iy = iy,
            Iz = iz,
            It = it,
            Iw = iw,
            Wply = wply,
            Wplz = wplz
        };
    }

    // NODOS
    public static async Task ReadNodes(JSAFProject project)
    {
        if (app == null || project == null) return;

        project.PointConnections = project.PointConnections ?? new List<PointConnection>();
        NodeMap = new Dictionary<int, string>();

        var nodeIds = await app.get_object_id_list(
            objectType: Rfem.ObjectType.Node
        );

        if (nodeIds == null || nodeIds.ObjectId.Count == 0) return;

        var nodeNumbers = nodeIds.ObjectId.Select(o => o.No).ToList();

        foreach (int nodeNo in nodeNumbers)
        {
            try
            {
                var node = await app.get_object<Rfem.StructureCore.Node>(
                    new Rfem.StructureCore.Node { No = nodeNo }
                );

                if (node == null) continue;

                string id = nodeNo.ToString();

                project.PointConnections.Add(new PointConnection
                {
                    Id = id,
                    Name = $"N{nodeNo}",
                    X = node.GlobalCoordinate1,
                    Y = node.GlobalCoordinate2,
                    Z = -node.GlobalCoordinate3
                });

                NodeMap[nodeNo] = id;
            }
            catch { continue; }
        }
    }


    // BARRAS
    public static async Task ReadMembers(JSAFProject project)
    {
        if (app == null || project == null) return;

        project.CurveMembers = project.CurveMembers ?? new List<CurveMember>();
        MemberMap = new Dictionary<int, string>();

        var memberIds = await app.get_object_id_list(
            objectType: Rfem.ObjectType.Member
        );

        if (memberIds == null || memberIds.ObjectId.Count == 0) return;

        var memberNumbers = memberIds.ObjectId.Select(o => o.No).ToList();

        foreach (int memNo in memberNumbers)
        {
            try
            {
                var mem = await app.get_object<Rfem.StructureCore.Member>(
                    new Rfem.StructureCore.Member { No = memNo }
                );

                if (mem == null) continue;

                string id = memNo.ToString();

                string node1 = mem.NodeStart.ToString();
                string node2 = mem.NodeEnd.ToString();

                // Sección vinculada
                string crossSectionId = string.Empty;
                try
                {
                    int secNo = mem.CrossSectionStart;
                    if (SectionMap.TryGetValue(secNo, out string? secId))
                        crossSectionId = secId;
                }
                catch { }

                // Tipo de miembro
                CurveMemberType memberType = CurveMemberType.General;
                try
                {
                    string memType = mem.Type.ToString().ToLower();
                    if (memType.Contains("column"))
                        memberType = CurveMemberType.Column;
                    else if (memType.Contains("beam") || memType.Contains("rib"))
                        memberType = CurveMemberType.Beam;
                }
                catch { }

                project.CurveMembers.Add(new CurveMember
                {
                    Id = id,
                    Name = $"Bar{memNo}",
                    Type = memberType,
                    Nodes = new List<string> { node1, node2 },
                    CrossSection = crossSectionId
                });

                MemberMap[memNo] = id;
            }
            catch { continue; }
        }
    }


    // APOYOS

    public static async Task ReadSupports(JSAFProject project)
    {
        if (app == null || project == null) return;

        project.PointSupports = project.PointSupports ?? new List<PointSupport>();

        var supportIds = await app.get_object_id_list(
            objectType: Rfem.ObjectType.NodalSupport
        );

        if (supportIds == null || supportIds.ObjectId.Count == 0) return;

        var supportNumbers = supportIds.ObjectId.Select(o => o.No).ToList();

        foreach (int supNo in supportNumbers)
        {
            try
            {
                var sup = await app.get_object<Rfem.TypesForNodes.NodalSupport>(
                    new Rfem.TypesForNodes.NodalSupport { No = supNo }
                );

                if (sup == null) continue;

                foreach (int nodeNo in sup.Nodes)
                {
                    string nodeId = NodeMap.TryGetValue(nodeNo, out string? nid) && nid != null
                        ? nid
                        : nodeNo.ToString();

                    project.PointSupports.Add(new NodalSupport
                    {
                        Id = Guid.NewGuid().ToString(),
                        Name = $"Sup{nodeNo}",
                        Node = nodeId,
                        Ux = MapSpringToTranslation(sup.SpringX),
                        Uy = MapSpringToTranslation(sup.SpringY),
                        Uz = MapSpringToTranslation(sup.SpringZ),
                        Fix = MapSpringToRotation(sup.RotationalRestraintX),
                        Fiy = MapSpringToRotation(sup.RotationalRestraintY),
                        Fiz = MapSpringToRotation(sup.RotationalRestraintZ)
                    });
                }
            }
            catch { continue; }
        }
    }

    private static PointTranslationRestrictions MapSpringToTranslation(double value)
    {
        if (double.IsPositiveInfinity(value)) return PointTranslationRestrictions.Rigid;
        if (value == 0) return PointTranslationRestrictions.Free;
        return PointTranslationRestrictions.Flexible;
    }

    private static PointRotationRestrictions MapSpringToRotation(double value)
    {
        if (double.IsPositiveInfinity(value)) return PointRotationRestrictions.Rigid;
        if (value == 0) return PointRotationRestrictions.Free;
        return PointRotationRestrictions.Flexible;
    }

    // SUPERFICIES 

    private static SurfaceMemberType DetectSurfaceType(List<string> nodeIds, JSAFProject project)
    {
        if (nodeIds.Count < 3 || project.PointConnections == null)
            return SurfaceMemberType.Shell;

        try
        {
            var nodeDict = new Dictionary<string, PointConnection>();
            foreach (var n in project.PointConnections)
                nodeDict[n.Id] = n;

            if (!nodeDict.TryGetValue(nodeIds[0], out var p0) ||
                !nodeDict.TryGetValue(nodeIds[1], out var p1) ||
                !nodeDict.TryGetValue(nodeIds[2], out var p2))
                return SurfaceMemberType.Shell;

            double ax = p1.X - p0.X, ay = p1.Y - p0.Y, az = p1.Z - p0.Z;
            double bx = p2.X - p0.X, by = p2.Y - p0.Y, bz = p2.Z - p0.Z;

            double nx = ay * bz - az * by;
            double ny = az * bx - ax * bz;
            double nz = ax * by - ay * bx;

            double len = Math.Sqrt(nx * nx + ny * ny + nz * nz);
            if (len < 1e-9) return SurfaceMemberType.Shell;

            nz = Math.Abs(nz / len);

            return nz > 0.7 ? SurfaceMemberType.Plate : SurfaceMemberType.Wall;
        }
        catch
        {
            return SurfaceMemberType.Shell;
        }
    }

    private static (double lcsx, double lcsy, double lcsz) ComputeLCSVector(List<string> nodeIds, JSAFProject project, SurfaceMemberType surfType)
    {
        if (nodeIds.Count < 2 || project.PointConnections == null)
            return (1, 0, 0);

        try
        {
            var nodeDict = new Dictionary<string, PointConnection>();
            foreach (var n in project.PointConnections)
                nodeDict[n.Id] = n;

            if (surfType == SurfaceMemberType.Plate)
            {
                if (!nodeDict.TryGetValue(nodeIds[0], out var pa) ||
                    !nodeDict.TryGetValue(nodeIds[1], out var pb))
                    return (1, 0, 0);

                double dx = pb.X - pa.X;
                double dy = pb.Y - pa.Y;
                double len = Math.Sqrt(dx * dx + dy * dy);
                if (len < 1e-9) return (1, 0, 0);
                return (dx / len, dy / len, 0);
            }

            for (int e = 0; e < nodeIds.Count; e++)
            {
                int next = (e + 1) % nodeIds.Count;
                if (!nodeDict.TryGetValue(nodeIds[e], out var pA) ||
                    !nodeDict.TryGetValue(nodeIds[next], out var pB))
                    continue;

                double dx = pB.X - pA.X;
                double dy = pB.Y - pA.Y;
                double dz = pB.Z - pA.Z;
                double lenH = Math.Sqrt(dx * dx + dy * dy);

                if (lenH > 1e-9)
                {
                    double lenFull = Math.Sqrt(dx * dx + dy * dy + dz * dz);
                    return (dx / lenFull, dy / lenFull, dz / lenFull);
                }
            }

            return (1, 0, 0);
        }
        catch
        {
            return (1, 0, 0);
        }
    }

    public static Dictionary<int, string> SurfaceMap { get; private set; } = new Dictionary<int, string>();

    public static async Task ReadSurfaces(JSAFProject project)
    {
        if (app == null || project == null) return;

        project.SurfaceMembers = project.SurfaceMembers ?? new List<SurfaceMember>();
        SurfaceMap = new Dictionary<int, string>();

        var surfaceIds = await app.get_object_id_list(
            objectType: Rfem.ObjectType.Surface
        );

        if (surfaceIds == null || surfaceIds.ObjectId.Count == 0) return;

        var surfaceNumbers = surfaceIds.ObjectId.Select(o => o.No).ToList();

        var thicknessCache = new Dictionary<int, int>();
        var lineCache = new Dictionary<int, List<int>>();

        foreach (int sfcNo in surfaceNumbers)
        {
            try
            {
                var sfc = await app.get_object<Rfem.StructureCore.Surface>(
                    new Rfem.StructureCore.Surface { No = sfcNo }
                );

                if (sfc == null) continue;

                string id = sfcNo.ToString();

                int thicknessMm = 200;
                try
                {
                    int thkNo = sfc.Thickness;
                    if (thkNo > 0)
                    {
                        if (!thicknessCache.TryGetValue(thkNo, out int cachedThk))
                        {
                            var thk = await app.get_object<Rfem.StructureCore.Thickness>(
                                new Rfem.StructureCore.Thickness { No = thkNo }
                            );
                            if (thk != null)
                            {
                                cachedThk = (int)(thk.UniformThickness * 1000);
                                thicknessCache[thkNo] = cachedThk;
                            }
                        }
                        if (cachedThk > 0) thicknessMm = cachedThk;
                    }
                }
                catch { }

                string materialId = string.Empty;
                try
                {
                    int matNo = sfc.Material;
                    if (matNo > 0 && MaterialMap.TryGetValue(matNo, out string? matId))
                        materialId = matId;
                }
                catch { }

                var nodeIds = new List<string>();
                try
                {
                    var linePairs = new List<(int a, int b)>();
                    foreach (int lineNo in sfc.BoundaryLines)
                    {
                        if (!lineCache.TryGetValue(lineNo, out List<int>? lineNodes))
                        {
                            var line = await app.get_object<Rfem.StructureCore.Line>(
                                new Rfem.StructureCore.Line { No = lineNo }
                            );
                            if (line != null)
                            {
                                lineNodes = line.DefinitionNodes.ToList();
                                lineCache[lineNo] = lineNodes;
                            }
                        }

                        if (lineNodes != null && lineNodes.Count >= 2)
                            linePairs.Add((lineNodes[0], lineNodes[1]));
                    }

                    if (linePairs.Count > 0)
                    {
                        var chain = new List<int> { linePairs[0].a, linePairs[0].b };
                        var used = new HashSet<int> { 0 };

                        while (used.Count < linePairs.Count)
                        {
                            int last = chain[chain.Count - 1];
                            bool found = false;
                            for (int i = 0; i < linePairs.Count; i++)
                            {
                                if (used.Contains(i)) continue;
                                if (linePairs[i].a == last)
                                {
                                    chain.Add(linePairs[i].b);
                                    used.Add(i);
                                    found = true;
                                    break;
                                }
                                if (linePairs[i].b == last)
                                {
                                    chain.Add(linePairs[i].a);
                                    used.Add(i);
                                    found = true;
                                    break;
                                }
                            }
                            if (!found) break;
                        }

                        if (chain.Count > 1 && chain[0] == chain[chain.Count - 1])
                            chain.RemoveAt(chain.Count - 1);

                        foreach (int nNo in chain)
                            nodeIds.Add(nNo.ToString());
                    }
                }
                catch { }

                if (nodeIds.Count < 3)
                {
                    nodeIds.Clear();
                    try
                    {
                        foreach (int lineNo in sfc.BoundaryLines)
                        {
                            if (!lineCache.TryGetValue(lineNo, out List<int>? lineNodes))
                            {
                                var line = await app.get_object<Rfem.StructureCore.Line>(
                                    new Rfem.StructureCore.Line { No = lineNo }
                                );
                                if (line != null)
                                {
                                    lineNodes = line.DefinitionNodes.ToList();
                                    lineCache[lineNo] = lineNodes;
                                }
                            }

                            if (lineNodes != null && lineNodes.Count > 0)
                                nodeIds.Add(lineNodes[0].ToString());
                        }

                        if (nodeIds.Count > 1 && nodeIds[0] == nodeIds[nodeIds.Count - 1])
                            nodeIds.RemoveAt(nodeIds.Count - 1);
                    }
                    catch { }
                }

                if (nodeIds.Count < 3) continue;

                SurfaceMemberType surfType = DetectSurfaceType(nodeIds, project);
                var (lcsx, lcsy, lcsz) = ComputeLCSVector(nodeIds, project, surfType);

                project.SurfaceMembers.Add(new SurfaceMember
                {
                    Id = id,
                    Name = $"S{sfcNo}",
                    Type = surfType,
                    Nodes = nodeIds,
                    Materials = string.IsNullOrEmpty(materialId)
                        ? new List<string>()
                        : new List<string> { materialId },
                    Thickness = thicknessMm,
                    InternalNodes = new List<string>(),
                    Edges = Enumerable.Repeat(SegmentType.Line, nodeIds.Count).ToList(),
                    LCS = LCSSurface.XByVector,
                    LCSX = lcsx,
                    LCSY = lcsy,
                    LCSZ = lcsz,
                    LCSRotation = 0,
                    SystemPlane = SystemPlane.Centre,
                    AnalyticBehavior = SurfaceMemberAnalyticBehavior.Isotropic
                });

                SurfaceMap[sfcNo] = id;
            }
            catch { continue; }
        }
    }
}
