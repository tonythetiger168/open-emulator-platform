// 4-bit conditional select benchmark: y <= neg ? (~a & m) : (a | m)
module sel4(clk, a, m, neg, y);
  input clk;
  input [3:0] a;
  input [3:0] m;
  input neg;
  output reg [3:0] y;
  wire [3:0] na;
  wire [3:0] oa;
  assign na = ~a & m;
  assign oa = a | m;
  always @(posedge clk) begin
    if (neg) y <= na;
    else     y <= oa;
  end
endmodule
