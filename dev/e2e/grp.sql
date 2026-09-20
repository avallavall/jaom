SELECT m.id, m.complete_name, m.action
FROM ir_ui_menu m
WHERE m.complete_name LIKE '%jaot%' OR m.action LIKE '%jaot%'
ORDER BY m.complete_name;
