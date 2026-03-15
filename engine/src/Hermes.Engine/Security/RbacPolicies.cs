namespace Hermes.Engine.Security;

/// <summary>
/// RBAC policy definitions for Hermes.
///
/// Roles:
/// - Viewer: read-only access (dashboards, logs, job details)
/// - Operator: manage recipes, reprocess jobs, activate pipelines
/// - Admin: full access including pipeline CRUD, definitions, user management
/// </summary>
public static class RbacPolicies
{
    // Permission names
    public const string ViewPipelines = "pipelines:view";
    public const string ManagePipelines = "pipelines:manage";
    public const string ActivatePipelines = "pipelines:activate";
    public const string ViewJobs = "jobs:view";
    public const string ReprocessJobs = "jobs:reprocess";
    public const string ViewRecipes = "recipes:view";
    public const string ManageRecipes = "recipes:manage";
    public const string ViewDefinitions = "definitions:view";
    public const string ManageDefinitions = "definitions:manage";
    public const string ViewLogs = "logs:view";
    public const string ManageSystem = "system:manage";
    public const string ViewDlq = "dlq:view";
    public const string ManageDlq = "dlq:manage";

    private static readonly Dictionary<Role, HashSet<string>> _rolePermissions = new()
    {
        [Role.Viewer] = new()
        {
            ViewPipelines, ViewJobs, ViewRecipes, ViewDefinitions, ViewLogs, ViewDlq
        },
        [Role.Operator] = new()
        {
            ViewPipelines, ActivatePipelines,
            ViewJobs, ReprocessJobs,
            ViewRecipes, ManageRecipes,
            ViewDefinitions,
            ViewLogs,
            ViewDlq, ManageDlq
        },
        [Role.Admin] = new()
        {
            ViewPipelines, ManagePipelines, ActivatePipelines,
            ViewJobs, ReprocessJobs,
            ViewRecipes, ManageRecipes,
            ViewDefinitions, ManageDefinitions,
            ViewLogs,
            ManageSystem,
            ViewDlq, ManageDlq
        }
    };

    public static bool HasPermission(Role role, string permission)
        => _rolePermissions.TryGetValue(role, out var perms) && perms.Contains(permission);

    public static HashSet<string> GetPermissions(Role role)
        => _rolePermissions.TryGetValue(role, out var perms) ? perms : new();
}
