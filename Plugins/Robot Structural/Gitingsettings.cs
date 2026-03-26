using System;
using System.IO;
using System.Text.Json;

namespace GithubConnect
{
    /// <summary>
    /// Persiste las credenciales de GitHub en el perfil del usuario de Windows:
    ///   %APPDATA%\GitING\settings.json
    ///
    /// No se requiere ninguna dependencia externa ni configuración de proyecto.
    /// El token se guarda en texto plano en una carpeta de usuario — adecuado
    /// para una herramienta de escritorio de ingeniería interna.
    /// </summary>
    public class GitIngSettings
    {
        private static readonly string _dir =
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "GitING");

        private static readonly string _file = Path.Combine(_dir, "settings.json");

        public string Owner { get; set; } = "";
        public string Repo { get; set; } = "";
        public string Token { get; set; } = "";

        // ── LOAD ──────────────────────────────────────────────────────────────
        public static GitIngSettings Load()
        {
            try
            {
                if (!File.Exists(_file)) return new GitIngSettings();
                var json = File.ReadAllText(_file);
                return JsonSerializer.Deserialize<GitIngSettings>(json) ?? new GitIngSettings();
            }
            catch
            {
                return new GitIngSettings();
            }
        }

        // ── SAVE ──────────────────────────────────────────────────────────────
        public void Save()
        {
            try
            {
                Directory.CreateDirectory(_dir);
                File.WriteAllText(_file, JsonSerializer.Serialize(this,
                    new JsonSerializerOptions { WriteIndented = true }));
            }
            catch { /* fallo silencioso — no crítico */ }
        }
    }
}