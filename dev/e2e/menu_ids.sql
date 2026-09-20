SELECT d.module || '.' || d.name AS xmlid, m.name AS menu, m.action
FROM ir_ui_menu m
JOIN ir_model_data d ON d.res_id = m.id AND d.model = 'ir.ui.menu'
WHERE d.module IN ('jaot_base', 'jaot_mrp', 'jaot_stock')
ORDER BY d.module, m.name;
