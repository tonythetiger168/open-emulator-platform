// Minimal 4-bit ALU-ish example for the efc MVP pipeline.
// sel=1 -> registered (a|b) ^ ~a ; sel=0 -> registered (a&b)
module alu4(clk, a, b, sel, y);
  input clk;
  input [3:0] a;
  input [3:0] b;
  input sel;
  output reg [3:0] y;

  wire [3:0] and_w;
  wire [3:0] or_w;
  wire [3:0] na_w;
  wire [3:0] alt_w;

  assign and_w = a & b;
  assign or_w  = a | b;
  assign na_w  = ~a;
  assign alt_w = or_w ^ na_w;

  always @(posedge clk) begin
    if (sel) y <= alt_w;
    else     y <= and_w;
  end
endmodule
