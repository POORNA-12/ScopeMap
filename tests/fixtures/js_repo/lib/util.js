function format(amount) {
  return "$" + amount;
}

function helper() {
  return format(0);
}

module.exports = { format, helper };
