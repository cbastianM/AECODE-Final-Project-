using System;
using System.IO;
using System.Runtime.Versioning;
using System.Windows.Forms;
using JSAF;
using JSAF.IO;
using SAP2000v1;

[assembly: SupportedOSPlatform("windows")]

class Program
{
    [STAThread]
    static void Main(string[] args)
    {
        cHelper helper = new Helper();
        cOAPI sapObject;

        try
        {
            sapObject = (cOAPI)helper.GetObject("CSI.SAP2000.API.SapObject");
        }
        catch
        {
            Console.WriteLine("No se pudo conectar a SAP2000. Asegurese de que esta abierto.");
            Console.ReadKey();
            return;
        }

        cSapModel sapModel = sapObject.SapModel;
        string modelName = sapModel.GetModelFilename(false);
        Console.WriteLine($"Conectado a: {modelName}");
        Console.WriteLine();

        var project = SAP2000JSafMapper.ProjectMapper(sapModel);

        Console.WriteLine($"=== RESUMEN ===");
        Console.WriteLine($"  Materiales:   {project.Materials?.Count ?? 0}");
        Console.WriteLine($"  Secciones:    {project.CrossSections?.Count ?? 0}");
        Console.WriteLine($"  Nodos:        {project.PointConnections?.Count ?? 0}");
        Console.WriteLine($"  Apoyos:       {project.PointSupports?.Count ?? 0}");
        Console.WriteLine($"  CurveMembers: {project.CurveMembers?.Count ?? 0}");
        Console.WriteLine($"  Surfaces:     {project.SurfaceMembers?.Count ?? 0}");
        Console.WriteLine($"  Regions:      {project.SurfaceMemberRegions?.Count ?? 0}");
        Console.WriteLine($"  {project.Description}");
        Console.WriteLine();

        string defaultName = Path.GetFileNameWithoutExtension(modelName) + "_JSAF.json";
        string defaultDir = Path.GetDirectoryName(modelName) ?? Environment.GetFolderPath(Environment.SpecialFolder.Desktop);

        var dialog = new SaveFileDialog
        {
            Title = "Guardar archivo JSAF",
            Filter = "JSON files (*.json)|*.json",
            FileName = defaultName,
            InitialDirectory = defaultDir
        };

        if (dialog.ShowDialog() == DialogResult.OK)
        {
            JSonSerializer.SerializeJsonFile(project, dialog.FileName);
            Console.WriteLine($"JSON guardado: {dialog.FileName}");
        }
        else
        {
            Console.WriteLine("Guardado cancelado.");
        }

        Console.ReadKey();
    }
}
