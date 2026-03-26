using RobotOM;
using System;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Animation;

namespace GithubConnect
{
    public partial class MainWindow : Window
    {
        private readonly IRobotApplication _robApp;
        private JsafProject _currentProject = null;
        private string _currentJson = null;
        private bool _isConnected = false;
        private GitHubService _github = null;
        private bool _drawerOpen = false;
        private readonly GitIngSettings _settings;

        private string _selectedBranch = null;

        private static readonly JsonSerializerOptions JsonOpts = new JsonSerializerOptions
        {
            WriteIndented = true,
            DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull
        };

        public MainWindow(IRobotApplication robApp)
        {
            InitializeComponent();
            _robApp = robApp;

            // Cargar credenciales guardadas
            _settings = GitIngSettings.Load();
            TxtOwner.Text = _settings.Owner;
            TxtRepo.Text = _settings.Repo;
            TxtToken.Password = _settings.Token;

            string projectName = _robApp.Project.Name ?? "Model";
            TxtProjectName.Text = Path.GetFileNameWithoutExtension(projectName);
            TxtModelName.Text = "Modelo-Base";
            TxtModelTitle.Text = Path.GetFileNameWithoutExtension(projectName);

            // Controles deshabilitados hasta tener datos / conexión
            BtnSaveLocal.IsEnabled = false;
            BtnPushGitHub.IsEnabled = false;
            BtnRefreshBranches.IsEnabled = false;
            SetPanelEnabled(PanelBranches, false);
            SetPanelEnabled(PanelCreateBranch, false);
            SetPanelEnabled(PanelUpload, false);

            // Live preview del nombre del archivo
            TxtModelName.TextChanged += (s, e) => UpdateFilePreview();
            TxtVersionNumber.TextChanged += (s, e) => UpdateFilePreview();
            TxtOriginVersion.TextChanged += (s, e) => UpdateFilePreview();
            TxtProjectName.TextChanged += (s, e) => UpdateFilePreview();

            Loaded += async (s, e) =>
            {
                await ExtractAsync();

                // Auto-conectar si hay credenciales guardadas
                if (!string.IsNullOrEmpty(_settings.Owner) &&
                    !string.IsNullOrEmpty(_settings.Repo) &&
                    !string.IsNullOrEmpty(_settings.Token))
                {
                    AppendLog("Credenciales guardadas detectadas — conectando automáticamente…");
                    BtnConnect_Click(this, new RoutedEventArgs());
                }
            };
        }

        // ── EXTRACT ────────────────────────────────────────────────────────────
        private async Task ExtractAsync()
        {
            try
            {
                SetStatus("Extrayendo geometría...", "#D97706");
                SetProgress("Extrayendo geometría del modelo…", 0, indeterminate: true);

                _currentProject = await Task.Run(() =>
                    GeometryMapper.Extract(_robApp, msg =>
                        Dispatcher.Invoke(() =>
                        {
                            AppendLog(msg);
                            // Progreso aproximado por fases reportadas en el log
                            if (msg.Contains("nodos")) SetProgress("Leyendo nodos…", 30);
                            else if (msg.Contains("barras")) SetProgress("Leyendo barras…", 60);
                            else if (msg.Contains("superf")) SetProgress("Leyendo superficies…", 85);
                        })
                    )
                );

                _currentJson = JsonSerializer.Serialize(_currentProject, JsonOpts);

                int nodes = _currentProject.PointConnections.Count;
                int bars = _currentProject.CurveMembers.Count;
                int surfs = _currentProject.SurfaceMembers.Count;

                SetProgress("Extracción completa", 100);
                await Task.Delay(800);
                HideProgress();

                TxtModelStats.Text = $"{nodes:N0} nodos · {bars:N0} barras · {surfs:N0} superficies";
                AppendLog($"Extraído: {nodes} nodos, {bars} barras, {surfs} superficies");
                AppendLog($"Tamaño JSON: {_currentJson.Length / 1024:N0} KB");
                SetStatus("Geometría lista — conecta con GitHub para publicar", "#8A9AB0");

                BtnSaveLocal.IsEnabled = true;
                UpdateFilePreview();
            }
            catch (Exception ex)
            {
                HideProgress();
                SetStatus($"Error: {ex.Message}", "#C0392B");
                AppendLog($"ERROR: {ex}");
            }
        }

        // ── DRAWER ─────────────────────────────────────────────────────────────
        private void BtnToggleDrawer_Click(object sender, RoutedEventArgs e)
        {
            if (_drawerOpen) CloseDrawer();
            else OpenDrawer();
        }

        private void Overlay_MouseDown(object sender, System.Windows.Input.MouseButtonEventArgs e)
        {
            CloseDrawer();
        }

        private void OpenDrawer()
        {
            _drawerOpen = true;
            Overlay.Visibility = Visibility.Visible;

            // Fade overlay in
            var fadeIn = new DoubleAnimation(0, 0.45, TimeSpan.FromMilliseconds(200));
            Overlay.BeginAnimation(OpacityProperty, fadeIn);

            // Slide drawer in from the right
            var slide = new DoubleAnimation(260, 0, TimeSpan.FromMilliseconds(220))
            {
                EasingFunction = new CubicEase { EasingMode = EasingMode.EaseOut }
            };
            DrawerTranslate.BeginAnimation(TranslateTransform.XProperty, slide);
        }

        private void CloseDrawer()
        {
            _drawerOpen = false;

            var fadeOut = new DoubleAnimation(0.45, 0, TimeSpan.FromMilliseconds(180));
            fadeOut.Completed += (s, e) => Overlay.Visibility = Visibility.Collapsed;
            Overlay.BeginAnimation(OpacityProperty, fadeOut);

            var slide = new DoubleAnimation(0, 260, TimeSpan.FromMilliseconds(200))
            {
                EasingFunction = new CubicEase { EasingMode = EasingMode.EaseIn }
            };
            DrawerTranslate.BeginAnimation(TranslateTransform.XProperty, slide);
        }

        // ── CONNECT ────────────────────────────────────────────────────────────
        private async void BtnConnect_Click(object sender, RoutedEventArgs e)
        {
            string owner = TxtOwner.Text.Trim();
            string repo = TxtRepo.Text.Trim();
            string token = TxtToken.Password.Trim();

            if (string.IsNullOrEmpty(owner) || string.IsNullOrEmpty(repo))
            {
                SetStatus("Completa usuario y repositorio.", "#C0392B"); return;
            }
            if (string.IsNullOrEmpty(token))
            {
                SetStatus("Ingresa el token de GitHub.", "#C0392B"); return;
            }

            BtnConnect.IsEnabled = false;
            SetStatus("Conectando con GitHub...", "#D97706");
            SetProgress("Verificando credenciales…", 0, indeterminate: true);

            try
            {
                _github = new GitHubService(token, owner, repo);
                var (success, info) = await _github.TestConnectionAsync();

                if (success)
                {
                    // Guardar credenciales para la próxima sesión
                    _settings.Owner = owner;
                    _settings.Repo = repo;
                    _settings.Token = TxtToken.Password.Trim();
                    _settings.Save();

                    _isConnected = true;
                    HideProgress();
                    SetStatus($"Conectado: {info}", "#2D7D3A");
                    AppendLog($"Conexión OK — {info}");
                    BtnConnect.Content = "Reconectar";

                    await LoadProjectBranchesAsync();

                    BtnRefreshBranches.IsEnabled = true;
                    SetPanelEnabled(PanelBranches, true);
                    SetPanelEnabled(PanelCreateBranch, true);
                    SetPanelEnabled(PanelUpload, true);
                }
                else
                {
                    _isConnected = false;
                    _github = null;
                    HideProgress();
                    SetStatus($"Fallo: {info}", "#C0392B");
                    AppendLog($"Error de conexión: {info}");
                    SetPanelEnabled(PanelBranches, false);
                    SetPanelEnabled(PanelCreateBranch, false);
                    SetPanelEnabled(PanelUpload, false);
                }
            }
            catch (Exception ex)
            {
                HideProgress();
                SetStatus($"Error: {ex.Message}", "#C0392B");
                AppendLog($"ERROR: {ex}");
            }
            finally
            {
                BtnConnect.IsEnabled = true;
            }
        }

        // ── REFRESH BRANCHES ───────────────────────────────────────────────────
        private async void BtnRefreshBranches_Click(object sender, RoutedEventArgs e)
        {
            await LoadProjectBranchesAsync(selectBranch: _selectedBranch);
        }

        // ── LOAD BRANCHES ─────────────────────────────────────────────────────
        private async Task LoadProjectBranchesAsync(string selectBranch = null)
        {
            if (_github == null) return;

            string projectName = TxtProjectName.Text.Trim();
            if (string.IsNullOrEmpty(projectName))
            {
                AppendLog("Escribe el nombre del proyecto primero.");
                return;
            }

            try
            {
                AppendLog($"Buscando ramas en: projects/{projectName}/");
                var (branches, error) = await _github.ListProjectBranchesAsync(projectName);

                if (error != null)
                {
                    AppendLog($"ERROR al listar ramas: {error}");
                    SetStatus("No se pudo leer la carpeta del proyecto. Ver log.", "#C0392B");
                    return;
                }

                var list = branches.Length > 0
                    ? branches.ToList()
                    : new System.Collections.Generic.List<string> { "main" };

                if (branches.Length == 0)
                    AppendLog("Carpeta vacía o no existe — se usará 'main' al publicar.");
                else
                    AppendLog($"Ramas encontradas ({list.Count}): {string.Join(", ", list)}");

                string toSelect = selectBranch
                    ?? _selectedBranch
                    ?? (list.Contains("main") ? "main" : list[0]);

                StackBranches.Children.Clear();
                _selectedBranch = null;

                foreach (var branch in list)
                {
                    var cb = new CheckBox
                    {
                        Content = branch,
                        Style = (Style)FindResource("BranchCheckBox"),
                        Tag = branch,
                        IsChecked = branch == toSelect
                    };
                    if (branch == toSelect) _selectedBranch = branch;
                    cb.Checked += BranchCheckBox_Checked;
                    cb.Unchecked += BranchCheckBox_Unchecked;
                    StackBranches.Children.Add(cb);
                }

                await RefreshNextVersionAsync();
                RefreshPushButton();
                UpdateSourceBranchLabel();
                UpdateFilePreview();
            }
            catch (Exception ex)
            {
                AppendLog($"Error al cargar ramas: {ex.Message}");
            }
        }

        // ── CHECKBOX selección única ───────────────────────────────────────────
        private async void BranchCheckBox_Checked(object sender, RoutedEventArgs e)
        {
            if (sender is not CheckBox clicked) return;

            foreach (var child in StackBranches.Children)
            {
                if (child is CheckBox cb && cb != clicked)
                {
                    cb.Checked -= BranchCheckBox_Checked;
                    cb.IsChecked = false;
                    cb.Checked += BranchCheckBox_Checked;
                }
            }

            _selectedBranch = clicked.Tag?.ToString();
            UpdateSourceBranchLabel();
            UpdateFilePreview();
            await RefreshNextVersionAsync();
            RefreshPushButton();
        }

        private void BranchCheckBox_Unchecked(object sender, RoutedEventArgs e)
        {
            if (sender is CheckBox cb && cb.Tag?.ToString() == _selectedBranch)
            {
                _selectedBranch = null;
                UpdateSourceBranchLabel();
                UpdateFilePreview();
                RefreshPushButton();
            }
        }

        // ── AUTO-VERSIÓN ───────────────────────────────────────────────────────
        private async Task RefreshNextVersionAsync()
        {
            if (_github == null || string.IsNullOrEmpty(_selectedBranch)) return;

            string projectName = TxtProjectName.Text.Trim();
            if (string.IsNullOrEmpty(projectName)) return;

            try
            {
                int next = await _github.GetNextVersionNumberAsync(projectName, _selectedBranch);
                TxtVersionNumber.Text = next.ToString();
                AppendLog($"Siguiente versión en '{_selectedBranch}': V{next}");
                UpdateFilePreview();
            }
            catch { TxtVersionNumber.Text = "1"; }
        }

        // ── CREATE BRANCH ──────────────────────────────────────────────────────
        private async void BtnCreateBranch_Click(object sender, RoutedEventArgs e)
        {
            if (!_isConnected || _github == null)
            {
                SetStatus("Conecta con GitHub primero.", "#C0392B"); return;
            }
            if (string.IsNullOrEmpty(_selectedBranch))
            {
                SetStatus("Selecciona una rama base.", "#C0392B"); return;
            }

            string newBranch = TxtNewBranch.Text.Trim().Replace(' ', '-');
            if (string.IsNullOrEmpty(newBranch) || newBranch == "feature/")
            {
                SetStatus("Escribe el nombre de la nueva rama.", "#C0392B"); return;
            }

            BtnCreateBranch.IsEnabled = false;
            SetStatus($"Creando '{newBranch}' desde '{_selectedBranch}'...", "#D97706");

            try
            {
                var (success, message) = await _github.CreateStructuralBranchAsync(
                    TxtProjectName.Text.Trim(), newBranch);

                if (success)
                {
                    SetStatus(message, "#2D7D3A");
                    AppendLog($"Rama creada: {message}");
                    await LoadProjectBranchesAsync(selectBranch: newBranch);
                    TxtNewBranch.Text = "feature/";
                }
                else
                {
                    SetStatus($"Error: {message}", "#C0392B");
                    AppendLog($"Error: {message}");
                }
            }
            catch (Exception ex) { SetStatus($"Error: {ex.Message}", "#C0392B"); }
            finally { BtnCreateBranch.IsEnabled = true; }
        }

        // ── SAVE LOCAL ─────────────────────────────────────────────────────────
        private void BtnSaveLocal_Click(object sender, RoutedEventArgs e)
        {
            if (string.IsNullOrEmpty(_currentJson)) { SetStatus("Sin datos.", "#C0392B"); return; }

            var dialog = new Microsoft.Win32.SaveFileDialog
            {
                FileName = BuildPreviewFilename() ?? "modelo.json",
                DefaultExt = ".json",
                Filter = "JSON files (*.json)|*.json"
            };

            if (dialog.ShowDialog() == true)
            {
                File.WriteAllText(dialog.FileName, _currentJson);
                SetStatus($"Guardado: {Path.GetFileName(dialog.FileName)}", "#2D7D3A");
                AppendLog($"Guardado local: {dialog.FileName}");
            }
        }

        // ── PUSH TO GITHUB ─────────────────────────────────────────────────────
        private async void BtnPushGitHub_Click(object sender, RoutedEventArgs e)
        {
            if (!_isConnected || _github == null)
            {
                SetStatus("Conecta con GitHub primero.", "#C0392B"); return;
            }
            if (string.IsNullOrEmpty(_currentJson)) { SetStatus("Sin datos.", "#C0392B"); return; }
            if (string.IsNullOrEmpty(_selectedBranch))
            {
                SetStatus("Selecciona una rama en Configuración.", "#C0392B"); return;
            }

            string projectName = TxtProjectName.Text.Trim();
            string modelName = TxtModelName.Text.Trim();
            string commitMsg = TxtCommitMsg.Text.Trim();

            if (string.IsNullOrEmpty(projectName) || string.IsNullOrEmpty(modelName))
            {
                SetStatus("Completa proyecto y nombre del modelo en Configuración.", "#C0392B");
                return;
            }

            if (!int.TryParse(TxtVersionNumber.Text.Trim(), out int versionNumber) || versionNumber < 1)
            {
                SetStatus("Número de versión inválido.", "#C0392B"); return;
            }

            int? originVersion = null;
            string originText = TxtOriginVersion.Text.Trim();
            if (!string.IsNullOrEmpty(originText))
            {
                if (int.TryParse(originText, out int ov) && ov > 0)
                    originVersion = ov;
                else
                {
                    SetStatus("Versión de origen inválida.", "#C0392B"); return;
                }
            }

            try
            {
                SetStatus($"Publicando V{versionNumber} en '{_selectedBranch}'...", "#D97706");
                BtnPushGitHub.IsEnabled = false;
                AppendLog($"Push → {projectName}/{_selectedBranch}/V{versionNumber}...");
                SetProgress("Serializando modelo…", 20);
                await Task.Delay(150);
                SetProgress("Conectando con GitHub…", 45);

                var (success, message) = await _github.UploadModelAsync(
                    projectName: projectName,
                    branch: _selectedBranch,
                    modelName: modelName,
                    versionNumber: versionNumber,
                    originVersion: originVersion,
                    jsonContent: _currentJson,
                    commitMessage: commitMsg
                );

                if (success)
                {
                    SetProgress("Publicado correctamente", 100);
                    await Task.Delay(900);
                    HideProgress();
                    SetStatus($"¡Publicado! {message}", "#2D7D3A");
                    AppendLog($"GitHub OK: {message}");
                    TxtVersionNumber.Text = (versionNumber + 1).ToString();
                    UpdateFilePreview();
                }
                else
                {
                    HideProgress();
                    SetStatus($"Fallo: {message}", "#C0392B");
                    AppendLog($"GitHub error: {message}");
                }
            }
            catch (Exception ex)
            {
                HideProgress();
                SetStatus($"Error: {ex.Message}", "#C0392B");
                AppendLog($"ERROR: {ex}");
            }
            finally { RefreshPushButton(); }
        }

        // ── HELPERS ────────────────────────────────────────────────────────────
        private void UpdateFilePreview()
        {
            string preview = BuildPreviewFilename();
            TxtFilePreview.Text = preview ?? "—";

            if (!string.IsNullOrEmpty(_selectedBranch))
            {
                string proj = TxtProjectName.Text.Trim();
                TxtBranchPreview.Text = string.IsNullOrEmpty(proj)
                    ? _selectedBranch
                    : $"{proj} / {_selectedBranch}";

                // Actualizar hint del botón push
                TxtPushHint.Text = preview != null
                    ? $"→ {_selectedBranch}"
                    : "Configura los datos primero";
            }
            else
            {
                TxtBranchPreview.Text = "—";
                TxtPushHint.Text = _isConnected
                    ? "Selecciona una rama"
                    : "Conecta GitHub primero";
            }
        }

        private string BuildPreviewFilename()
        {
            if (!int.TryParse(TxtVersionNumber.Text.Trim(), out int v)) return null;
            string name = TxtModelName.Text.Trim().Replace(' ', '-');
            if (string.IsNullOrEmpty(name)) return null;
            string origin = TxtOriginVersion.Text.Trim();

            bool isFeature = !string.Equals(_selectedBranch, "main",
                                 StringComparison.OrdinalIgnoreCase)
                             && int.TryParse(origin, out int ov) && ov > 0;

            return isFeature ? $"V{v}_V{origin}_{name}.json" : $"V{v}_{name}.json";
        }

        private void RefreshPushButton()
        {
            BtnPushGitHub.IsEnabled = _isConnected
                                      && _currentJson != null
                                      && !string.IsNullOrEmpty(_selectedBranch);
        }

        private void UpdateSourceBranchLabel()
        {
            if (string.IsNullOrEmpty(_selectedBranch))
            {
                TxtSourceBranchLabel.Text = "(selecciona una rama)";
                TxtSourceBranchLabel.FontStyle = FontStyles.Italic;
                TxtSourceBranchLabel.Foreground =
                    new SolidColorBrush(Color.FromRgb(0x64, 0x74, 0x8b));
            }
            else
            {
                TxtSourceBranchLabel.Text = _selectedBranch;
                TxtSourceBranchLabel.FontStyle = FontStyles.Normal;
                TxtSourceBranchLabel.Foreground =
                    new SolidColorBrush(Color.FromRgb(0x4a, 0xde, 0x80));
            }
        }

        private void SetPanelEnabled(UIElement panel, bool enabled)
        {
            panel.IsEnabled = enabled;
            panel.Opacity = enabled ? 1.0 : 0.5;
        }

        // ── PROGRESS ───────────────────────────────────────────────────────────
        /// <summary>
        /// Muestra la barra de progreso con un valor (0–100) y una etiqueta.
        /// Llamar con value=0 pone la barra en modo indeterminado (pulso).
        /// </summary>
        private void SetProgress(string label, double value, bool indeterminate = false)
        {
            PanelProgress.Visibility = Visibility.Visible;
            TxtProgressLabel.Text = label;
            ProgressBar.IsIndeterminate = indeterminate;

            if (!indeterminate)
            {
                ProgressBar.Value = value;
                TxtProgressPct.Text = $"{(int)value} %";
                TxtProgressPct.Foreground = value >= 100
                    ? new SolidColorBrush(Color.FromRgb(0x2D, 0x7D, 0x3A))   // verde al terminar
                    : new SolidColorBrush(Color.FromRgb(0x1A, 0x3A, 0x6E));  // azul en curso
                ProgressBar.Foreground = value >= 100
                    ? new SolidColorBrush(Color.FromRgb(0x2D, 0x7D, 0x3A))
                    : new SolidColorBrush(Color.FromRgb(0x1A, 0x3A, 0x6E));
            }
            else
            {
                TxtProgressPct.Text = "…";
                TxtProgressPct.Foreground = new SolidColorBrush(Color.FromRgb(0x8A, 0x9A, 0xB0));
            }
        }

        private void HideProgress()
        {
            PanelProgress.Visibility = Visibility.Collapsed;
            ProgressBar.Value = 0;
            ProgressBar.IsIndeterminate = false;
        }

        private void SetStatus(string text, string hexColor)
        {
            TxtStatus.Text = text;
            try
            {
                TxtStatus.Foreground = new SolidColorBrush(
                    (Color)ColorConverter.ConvertFromString(hexColor));
            }
            catch { }
        }

        private void AppendLog(string line)
        {
            TxtLog.Text += $"[{DateTime.Now:HH:mm:ss}] {line}\n";
            LogScroll.ScrollToBottom();
        }
    }
}