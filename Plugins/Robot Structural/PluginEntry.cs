using RobotOM;
using System;
using System.Runtime.InteropServices;

namespace GithubConnect
{
    public static class PluginEntry
    {
        [DllImport("oleaut32.dll", PreserveSig = false)]
        private static extern void GetActiveObject(
            [MarshalAs(UnmanagedType.LPStruct)] Guid clsid,
            IntPtr reserved,
            [MarshalAs(UnmanagedType.IUnknown)] out object obj);

        private static object GetCOMObject(string progId)
        {
            var type = Type.GetTypeFromProgID(progId);
            if (type == null) throw new Exception($"ProgID '{progId}' not found.");
            GetActiveObject(type.GUID, IntPtr.Zero, out object obj);
            return obj;
        }

        [STAThread]
        public static void Run()
        {
            try
            {
                var robApp = new RobotApplication();

                if (robApp == null || robApp.Project == null || robApp.Project.Structure == null)
                {
                    System.Windows.MessageBox.Show(
                        "No se pudo conectar a Robot o no hay proyecto abierto.",
                        "JSAF Export", System.Windows.MessageBoxButton.OK, System.Windows.MessageBoxImage.Error);
                    return;
                }

                var window = new MainWindow(robApp);

                if (System.Windows.Application.Current == null)
                {
                    var app = new System.Windows.Application();
                    app.Run(window);
                }
                else
                {
                    window.ShowDialog();
                }
            }
            catch (Exception ex)
            {
                System.Windows.MessageBox.Show(
                    $"Error:\n{ex.Message}",
                    "JSAF Export", System.Windows.MessageBoxButton.OK, System.Windows.MessageBoxImage.Error);
            }
        }
    }
}