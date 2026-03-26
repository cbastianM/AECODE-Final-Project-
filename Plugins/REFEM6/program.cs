using JSAF;
using JSAF.IO;

class Program
{
    static async Task Main(string[] args)
    {
        string apiKey = Environment.GetEnvironmentVariable("RFEM_API_KEY") ?? string.Empty; if (string.IsNullOrEmpty(apiKey))
        {
            System.Windows.MessageBox.Show("No se encontró la variable de entorno RFEM_API_KEY", "Error");
            return;
        }

        var project = new JSAFProject();
        
    await RfemMapper.ReadMaterials(project);
    await RfemMapper.ReadCrossSections(project);
    await RfemMapper.ReadNodes(project);
    await RfemMapper.ReadMembers(project);
    await RfemMapper.ReadSupports(project);
    await RfemMapper.ReadSurfaces(project);
    await RfemMapper.CloseConnection();

        
        string? savePath = ShowSaveDialogSTA();
        if (savePath == null) return;
        JSonSerializer.SerializeJsonFile(project, savePath);
    }

    static string? ShowSaveDialogSTA()
    {
        string? result = null;
        var thread = new System.Threading.Thread(() =>
        {
            result = FileDialogsHelper.SelectJsonSavePath();
        });
        thread.SetApartmentState(System.Threading.ApartmentState.STA);
        thread.Start();
        thread.Join();
        return result;
    }
}
