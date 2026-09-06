const { format } = require("../lib/util");

function total(items) {
  return format(items.length);
}

module.exports = { total };
