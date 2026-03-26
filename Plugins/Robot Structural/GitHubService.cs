using System;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace GithubConnect
{
    /// <summary>
    /// Manages JSAF model files in a fixed GitHub repository.
    ///
    /// Folder structure:
    ///   projects/{ProjectName}/{branch}/V{n}_{name}.json          (main branch)
    ///   projects/{ProjectName}/{branch}/V{n}_V{origin}_{name}.json (feature branches)
    ///
    /// Example:
    ///   projects/Mi-Proyecto/main/V1_Modelo-Base.json
    ///   projects/Mi-Proyecto/main/V2_Ampliacion.json
    ///   projects/Mi-Proyecto/feature-postensado/V3_V2_Losa-Postensada.json
    /// </summary>
    public class GitHubService
    {
        private const string API_BASE = "https://api.github.com";
        private const string PROJECTS_DIR = "projects";

        private readonly HttpClient _http;
        private readonly string _owner;
        private readonly string _repo;

        /// <param name="token">GitHub personal-access token (repo scope).</param>
        /// <param name="owner">Cuenta u organización dueña del repositorio.</param>
        /// <param name="repo">Nombre del repositorio.</param>
        public GitHubService(string token, string owner, string repo)
        {
            _owner = owner.Trim();
            _repo = repo.Trim();
            _http = new HttpClient();
            _http.DefaultRequestHeaders.Authorization =
                new AuthenticationHeaderValue("Bearer", token);
            _http.DefaultRequestHeaders.UserAgent.ParseAdd("GitING-Plugin/1.0");
            _http.DefaultRequestHeaders.Accept.Add(
                new MediaTypeWithQualityHeaderValue("application/vnd.github+json"));
        }

        // ══════════════════════════════════════════════════════════════════════
        //  PUBLIC API
        // ══════════════════════════════════════════════════════════════════════

        // ── UPLOAD MODEL ──────────────────────────────────────────────────────
        /// <summary>
        /// Uploads a JSAF model to:
        ///   projects/{projectName}/{structuralBranch}/V{n}_{modelName}.json
        ///
        /// IMPORTANT: structural branches are FOLDERS inside the Git repo,
        /// not Git branches. All commits go to the Git 'main' branch.
        /// </summary>
        public async Task<(bool success, string message)> UploadModelAsync(
            string projectName,
            string branch,
            string modelName,
            int versionNumber,
            int? originVersion,
            string jsonContent,
            string commitMessage = null)
        {
            try
            {
                // Structural branch = folder name, NOT a Git branch
                string filename = BuildFilename(branch, modelName, versionNumber, originVersion);
                string path = $"{PROJECTS_DIR}/{Sanitize(projectName)}/{Sanitize(branch)}/{filename}";

                // Always commit to Git main — the folder IS the structural branch
                const string GIT_BRANCH = "main";

                if (string.IsNullOrWhiteSpace(commitMessage))
                    commitMessage = $"[{projectName}/{branch}] {filename} — {DateTime.Now:yyyy-MM-dd HH:mm}";

                // SHA needed only when updating an existing file
                string sha = await GetFileShaAsync(path, GIT_BRANCH);

                string base64 = Convert.ToBase64String(Encoding.UTF8.GetBytes(jsonContent));

                var body = sha != null
                    ? new { message = commitMessage, content = base64, branch = GIT_BRANCH, sha }
                    : (object)new { message = commitMessage, content = base64, branch = GIT_BRANCH };

                var putUrl = $"{API_BASE}/repos/{_owner}/{_repo}/contents/{path}";
                var request = new HttpRequestMessage(HttpMethod.Put, putUrl)
                {
                    Content = new StringContent(
                        JsonSerializer.Serialize(body), Encoding.UTF8, "application/json")
                };

                var resp = await _http.SendAsync(request);
                if (resp.IsSuccessStatusCode)
                {
                    var respJson = await resp.Content.ReadAsStringAsync();
                    using var doc = JsonDocument.Parse(respJson);
                    var commitSha = doc.RootElement
                                      .GetProperty("commit")
                                      .GetProperty("sha")
                                      .GetString();
                    string shortSha = commitSha?.Length >= 8 ? commitSha[..8] : "?";
                    return (true, $"✔ {shortSha} → {projectName}/{branch}/{filename}");
                }

                var error = await resp.Content.ReadAsStringAsync();
                return (false, $"HTTP {(int)resp.StatusCode}: {error}");
            }
            catch (Exception ex)
            {
                return (false, ex.Message);
            }
        }

        // ── LIST PROJECTS ─────────────────────────────────────────────────────
        /// <summary>Returns the list of project folders inside /projects/.</summary>
        public async Task<string[]> ListProjectsAsync()
        {
            var (items, _) = await ListFolderContentsAsync(PROJECTS_DIR, type: "dir");
            return items;
        }

        /// <summary>
        /// Returns the structural branch folders inside a project.
        /// Result includes an error string (null = success) for UI logging.
        /// </summary>
        public async Task<(string[] branches, string error)> ListProjectBranchesAsync(string projectName)
        {
            string path = $"{PROJECTS_DIR}/{Sanitize(projectName)}";
            return await ListFolderContentsAsync(path, type: "dir");
        }

        public async Task<string[]> ListVersionsAsync(string projectName, string branch)
        {
            string path = $"{PROJECTS_DIR}/{Sanitize(projectName)}/{Sanitize(branch)}";
            var (files, _) = await ListFolderContentsAsync(path, type: "file");
            Array.Sort(files, StringComparer.OrdinalIgnoreCase);
            return files;
        }

        // ── DOWNLOAD VERSION ──────────────────────────────────────────────────
        /// <summary>Downloads the raw JSON content of a specific version file.</summary>
        public async Task<(bool success, string content)> DownloadVersionAsync(
            string projectName, string branch, string filename)
        {
            try
            {
                string path = $"{PROJECTS_DIR}/{Sanitize(projectName)}/{Sanitize(branch)}/{filename}";
                string getUrl = $"{API_BASE}/repos/{_owner}/{_repo}/contents/{path}";

                var resp = await _http.GetAsync(getUrl);
                if (!resp.IsSuccessStatusCode)
                    return (false, $"HTTP {(int)resp.StatusCode}");

                var json = await resp.Content.ReadAsStringAsync();
                using var doc = JsonDocument.Parse(json);

                // GitHub returns file content as base64
                string base64 = doc.RootElement.GetProperty("content").GetString() ?? "";
                string decoded = Encoding.UTF8.GetString(
                    Convert.FromBase64String(base64.Replace("\n", "")));

                return (true, decoded);
            }
            catch (Exception ex)
            {
                return (false, ex.Message);
            }
        }

        // ── NEXT VERSION NUMBER ───────────────────────────────────────────────
        /// <summary>
        /// Reads existing files in a branch folder and returns the next available
        /// version number (max existing + 1), starting at 1 if the folder is empty.
        /// </summary>
        public async Task<int> GetNextVersionNumberAsync(string projectName, string branch)
        {
            var versions = await ListVersionsAsync(projectName, branch);
            int max = 0;
            foreach (var f in versions)
            {
                // File names: V{n}_... or V{n}_V{m}_...
                var m = Regex.Match(f, @"^V(\d+)_", RegexOptions.IgnoreCase);
                if (m.Success && int.TryParse(m.Groups[1].Value, out int n))
                    max = Math.Max(max, n);
            }
            return max + 1;
        }

        // ── CREATE STRUCTURAL BRANCH (carpeta) ───────────────────────────────
        /// <summary>
        /// Creates a new structural branch by creating its folder in the repo.
        /// Since Git doesn't track empty folders, commits a .gitkeep placeholder.
        /// Path: projects/{projectName}/{newBranch}/.gitkeep  →  Git branch: main
        /// </summary>
        public async Task<(bool success, string message)> CreateStructuralBranchAsync(
            string projectName, string newBranch)
        {
            try
            {
                string safeName = Sanitize(newBranch);
                string path = $"{PROJECTS_DIR}/{Sanitize(projectName)}/{safeName}/.gitkeep";

                // Abort if folder already exists
                if (await GetFileShaAsync(path, "main") != null)
                    return (false, $"La rama estructural '{newBranch}' ya existe.");

                string content = Convert.ToBase64String(
                    Encoding.UTF8.GetBytes($"# Rama estructural GitING: {newBranch}\n"));

                var body = JsonSerializer.Serialize(new
                {
                    message = $"[{projectName}] Crear rama estructural '{newBranch}'",
                    content,
                    branch = "main"
                });

                var putUrl = $"{API_BASE}/repos/{_owner}/{_repo}/contents/{path}";
                var request = new HttpRequestMessage(HttpMethod.Put, putUrl)
                {
                    Content = new StringContent(body, Encoding.UTF8, "application/json")
                };

                var resp = await _http.SendAsync(request);

                if (resp.IsSuccessStatusCode)
                    return (true, $"Rama '{newBranch}' creada en {projectName}/");

                var error = await resp.Content.ReadAsStringAsync();
                return (false, $"HTTP {(int)resp.StatusCode}: {error}");
            }
            catch (Exception ex)
            {
                return (false, ex.Message);
            }
        }

        // ── TEST CONNECTION ───────────────────────────────────────────────────
        public async Task<(bool success, string repoFullName)> TestConnectionAsync()
        {
            try
            {
                var url = $"{API_BASE}/repos/{_owner}/{_repo}";
                var resp = await _http.GetAsync(url);
                if (resp.IsSuccessStatusCode)
                {
                    using var doc = JsonDocument.Parse(await resp.Content.ReadAsStringAsync());
                    return (true, doc.RootElement.GetProperty("full_name").GetString() ?? "");
                }
                return (false, $"HTTP {(int)resp.StatusCode}");
            }
            catch (Exception ex)
            {
                return (false, ex.Message);
            }
        }

        // ══════════════════════════════════════════════════════════════════════
        //  PRIVATE HELPERS
        // ══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Builds a filename following the GitING versioning convention:
        ///   main / any branch without origin → V{n}_{name}.json
        ///   feature branch with origin      → V{n}_V{origin}_{name}.json
        /// </summary>
        private static string BuildFilename(
            string branch, string modelName, int version, int? originVersion)
        {
            string safeName = Sanitize(modelName);

            bool isFeature = !string.Equals(branch, "main", StringComparison.OrdinalIgnoreCase)
                             && originVersion.HasValue && originVersion.Value > 0;

            return isFeature
                ? $"V{version}_V{originVersion}_{safeName}.json"
                : $"V{version}_{safeName}.json";
        }

        /// <summary>
        /// Replaces spaces with hyphens and strips characters that are not safe
        /// in GitHub paths or file names.
        /// </summary>
        private static string Sanitize(string value)
        {
            if (string.IsNullOrWhiteSpace(value)) return "sin-nombre";
            value = value.Trim().Replace(' ', '-');
            // Keep letters, digits, hyphens, underscores, dots
            return Regex.Replace(value, @"[^A-Za-z0-9\-_\.]", "");
        }

        /// <summary>Gets the SHA of an existing file (needed for updates). Always checks in main.</summary>
        private async Task<string> GetFileShaAsync(string path, string gitBranch = "main")
        {
            try
            {
                var url = $"{API_BASE}/repos/{_owner}/{_repo}/contents/{path}?ref={gitBranch}";
                var resp = await _http.GetAsync(url);
                if (!resp.IsSuccessStatusCode) return null;

                using var doc = JsonDocument.Parse(await resp.Content.ReadAsStringAsync());
                return doc.RootElement.GetProperty("sha").GetString();
            }
            catch
            {
                return null;
            }
        }

        /// <summary>
        /// Lists names of items of a given type inside a GitHub contents folder.
        /// Returns (items, errorMessage). errorMessage is null on success.
        /// </summary>
        private async Task<(string[] items, string error)> ListFolderContentsAsync(
            string path, string type = "file")
        {
            var url = $"{API_BASE}/repos/{_owner}/{_repo}/contents/{path}?ref=main";
            HttpResponseMessage resp;

            try { resp = await _http.GetAsync(url); }
            catch (Exception ex) { return (Array.Empty<string>(), $"Red: {ex.Message}"); }

            if (!resp.IsSuccessStatusCode)
            {
                string body = await resp.Content.ReadAsStringAsync();
                return (Array.Empty<string>(),
                    $"HTTP {(int)resp.StatusCode} — URL: {url} — {body}");
            }

            try
            {
                var results = new List<string>();
                var json = await resp.Content.ReadAsStringAsync();
                using var doc = JsonDocument.Parse(json);

                foreach (var item in doc.RootElement.EnumerateArray())
                {
                    if (item.GetProperty("type").GetString() == type)
                        results.Add(item.GetProperty("name").GetString() ?? "");
                }

                return (results.ToArray(), null);
            }
            catch (Exception ex)
            {
                return (Array.Empty<string>(), $"Parse error: {ex.Message}");
            }
        }
    }
}