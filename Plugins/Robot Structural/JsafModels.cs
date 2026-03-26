using System;
using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace GithubConnect
{
    public class JsafProject
    {
        public string Name { get; set; } = "";
        public string Description { get; set; } = "";
        public List<Material> Materials { get; set; } = new List<Material>();
        public List<CrossSection> CrossSections { get; set; } = new List<CrossSection>();
        public List<PointConnection> PointConnections { get; set; } = new List<PointConnection>();
        public List<CurveMember> CurveMembers { get; set; } = new List<CurveMember>();
        public List<SurfaceMember> SurfaceMembers { get; set; } = new List<SurfaceMember>();
    }

    public class Material
    {
        public string Id { get; set; } = "";
        public string Name { get; set; } = "";
        public string Type { get; set; } = "";
        public double EModulus { get; set; }
        public double PoissonCoefficient { get; set; }
        public double UnitMass { get; set; }
        public double ThermalExpansion { get; set; }
        public double GModulus { get; set; }
        [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingDefault)]
        public double Fck { get; set; }
        [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingDefault)]
        public double Fy { get; set; }
        [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingDefault)]
        public double Fu { get; set; }
    }

    public class CrossSection
    {
        public string Id { get; set; } = "";
        public string Name { get; set; } = "";
        public string Shape { get; set; } = "";
        public List<double> Parameters { get; set; } = new List<double>();
        public List<string> Materials { get; set; } = new List<string>();
    }

    public class PointConnection
    {
        public string Id { get; set; } = "";
        public string Name { get; set; } = "";
        public double X { get; set; }
        public double Y { get; set; }
        public double Z { get; set; }
    }

    public class CurveMember
    {
        public string Id { get; set; } = "";
        public string Name { get; set; } = "";
        public string Type { get; set; } = "";
        public List<string> Nodes { get; set; } = new List<string>();
        public string CrossSection { get; set; } = "";
    }

    public class SurfaceMember
    {
        public string Id { get; set; } = "";
        public string Name { get; set; } = "";
        public string Type { get; set; } = "";
        public List<string> Nodes { get; set; } = new List<string>();
        public List<string> Materials { get; set; } = new List<string>();
        public int Thickness { get; set; }
    }
}