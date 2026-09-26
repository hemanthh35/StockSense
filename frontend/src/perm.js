// Roles, lowest to highest. The server enforces these rules; the UI only hides what a person cannot use.
//   staff   - warehouse staff: see everything, run transfers, pick/pack/validate, count stock
//   manager - inventory manager: also create/edit documents, products, contacts, import, reorder
//   admin   - everything, plus warehouses, locations, taxes, users and the activity log
export const RANK = { staff: 1, manager: 2, admin: 3 }
export const ROLE_LABEL = { staff: 'Warehouse staff', manager: 'Inventory manager', admin: 'Administrator' }

export const atLeast = (user, role) => (RANK[user?.role] || 0) >= RANK[role]

/** Can this user create/edit/cancel/duplicate documents of the given type (IN, OUT, INT, ADJ)? */
export const canEditDocs = (user, type) => (type === 'INT' ? atLeast(user, 'staff') : atLeast(user, 'manager'))
